"""H3.2: Gemini simulado; base de test aislada y llamadas sin transacciones."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier, Event
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import Mock, patch
import json

from django.db import close_old_connections, connection, connections, transaction
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from google.genai import types

from core.models import (AliasURLPublicacion, Locacion, ProcesamientoIAMultifuente,
                         Publicacion, PublicacionEtiqueta, PublicacionTema, RegistroDatos, Sentimiento)
from core.services import gemini_multifuente as ia
from core.services.fuentes_rss import FUENTES_RSS
from core.services.gemini_cliente import GeminiCliente
from core.services.lector_rss import NoticiaRSS
from core.services.persistencia_multifuente import persistir_lote


class GeminiMultifuenteTests(TransactionTestCase):
    def setUp(self):
        f = FUENTES_RSS[0]
        self.noticia = NoticiaRSS(f.nombre, f.identificador, 'Hospital de San Pedro amplía vacunación',
                                 'https://misionesonline.net/nueva', None, '',
                                 'El hospital de San Pedro anunció nuevas jornadas de vacunación y controles de salud '
                                 'para las familias. Los médicos atenderán consultas durante la semana y organizarán '
                                 'actividades para mejorar la atención de los vecinos de la localidad.', 'salud')
        self.data = dict(polaridad=0.4, confianza=0.9,
                         localidades=[dict(nombre='San Pedro', latitud=-26.62, longitud=-54.11)])
        self.sdk = Mock()
        self.sdk.models.generate_content.return_value.text = json.dumps(self.data)
        self.cliente = SimpleNamespace(client=self.sdk, types=types, model_name='modelo-configurado')
        autorizacion = override_settings(GEMINI_MULTIFUENTE_FUENTES_AUTORIZADAS=(f.identificador,))
        autorizacion.enable()
        self.addCleanup(autorizacion.disable)
        for destino in ('socket.getaddrinfo', 'socket.socket.connect', 'socket.socket.connect_ex',
                        'core.services.descarga_segura.descargar',
                        'core.services.clasificacion._clasificar_con_ia'):
            parche = patch(destino, side_effect=AssertionError('Red e IA de clasificación prohibidas'))
            parche.start()
            self.addCleanup(parche.stop)

    def guardar(self):
        return persistir_lote([self.noticia])

    def procesar(self, recibo, **kwargs):
        return ia.procesar_nuevas(recibo, cliente=self.cliente, pausa_segundos=0, **kwargs)

    def test_solo_ids_creados_excluye_duplicados_rechazados_e_historicos(self):
        historica = Publicacion.objects.create(hash_origen='historica', titulo='Anterior', contenido='Texto')
        recibo = persistir_lote([self.noticia, self.noticia, replace(self.noticia, titulo='')])
        resultado = self.procesar(recibo)
        self.assertEqual((resultado['procesadas'], resultado['llamadas']), (1, 1))
        self.assertEqual(resultado['errores'], [])
        historica.refresh_from_db()
        self.assertFalse(historica.procesado_ia)
        pub = Publicacion.objects.exclude(pk=historica.pk).get()
        self.assertEqual(Sentimiento.objects.get().id_publicacion_api_id, pub.pk)
        self.assertEqual(Locacion.objects.get().location, 'San Pedro')
        self.assertEqual(ProcesamientoIAMultifuente.objects.get().estado, 'COMPLETADO')

    def test_orquestacion_no_procesa_duplicados_en_reintentos(self):
        a = ia.persistir_y_procesar([self.noticia], cliente=self.cliente, pausa_segundos=0)
        b = ia.persistir_y_procesar([self.noticia], cliente=self.cliente, pausa_segundos=0)
        self.assertEqual(a['ia']['procesadas'], 1)
        self.assertEqual(b['ia']['llamadas'], 0)
        self.procesar(a['ingesta'])
        self.sdk.models.generate_content.assert_called_once()

    def test_llamada_fuera_de_transaccion_y_reserva_ya_confirmada(self):
        recibo = self.guardar()
        def llamar(**kwargs):
            self.assertFalse(connection.in_atomic_block)
            self.assertTrue(connection.get_autocommit())
            self.assertEqual(ProcesamientoIAMultifuente.objects.get().estado, 'EN_PROCESO')
            return SimpleNamespace(text=json.dumps(self.data))
        self.sdk.models.generate_content.side_effect = llamar
        self.assertEqual(self.procesar(recibo)['procesadas'], 1)
        config = self.sdk.models.generate_content.call_args.kwargs['config']
        self.assertEqual(config.http_options.retry_options.attempts, 1)
        self.assertEqual(config.http_options.timeout, 30000)
        self.assertEqual(self.sdk.models.generate_content.call_args.kwargs['model'], 'modelo-configurado')

    def test_transaccion_externa_rechazada_antes_de_persistir_o_llamar(self):
        with transaction.atomic():
            with self.assertRaises(ValueError):
                ia.persistir_y_procesar([self.noticia], cliente=self.cliente)
        self.assertFalse(Publicacion.objects.exists())
        self.sdk.models.generate_content.assert_not_called()

    def test_clasificacion_y_etiquetas_se_conservan(self):
        recibo = self.guardar()
        pub = Publicacion.objects.get()
        antes = dict(departamento=pub.departamento, titulo=pub.titulo, contenido=pub.contenido)
        etiquetas = list(PublicacionEtiqueta.objects.values_list('pk', 'etiqueta_id', 'posicion'))
        temas = list(PublicacionTema.objects.values_list('pk', 'id_temas_id'))
        self.procesar(recibo)
        pub.refresh_from_db()
        for campo, valor in antes.items():
            self.assertEqual(getattr(pub, campo), valor)
        self.assertEqual(list(PublicacionEtiqueta.objects.values_list('pk', 'etiqueta_id', 'posicion')), etiquetas)
        self.assertEqual(list(PublicacionTema.objects.values_list('pk', 'id_temas_id')), temas)

    def test_timeout_no_borra_publicacion_y_no_reenvia_en_reintento(self):
        recibo = self.guardar()
        self.sdk.models.generate_content.side_effect = TimeoutError('Respuesta incierta')
        resultado = self.procesar(recibo)
        self.assertEqual(resultado['errores'][0]['codigo'], 'llamada_gemini')
        self.assertEqual(ProcesamientoIAMultifuente.objects.get().estado, 'INCIERTO')
        self.assertEqual(Publicacion.objects.count(), 1)
        self.assertFalse(Publicacion.objects.get().procesado_ia)
        self.assertFalse(Sentimiento.objects.exists())
        self.procesar(recibo)
        self.sdk.models.generate_content.assert_called_once()

    def test_respuesta_invalida_no_se_guarda_ni_se_reenvia(self):
        recibo = self.guardar()
        self.sdk.models.generate_content.return_value.text = '{malformado}'
        resultado = self.procesar(recibo)
        self.assertEqual(resultado['errores'][0]['codigo'], 'validacion_respuesta')
        self.assertFalse(Sentimiento.objects.exists())
        self.procesar(recibo)
        self.sdk.models.generate_content.assert_called_once()

    def test_fallo_de_guardado_revierte_resultados_pero_conserva_noticia_y_reserva(self):
        recibo = self.guardar()
        with patch.object(Locacion.objects, 'create', side_effect=RuntimeError('Fallo de BD simulado')):
            self.procesar(recibo)
        self.assertFalse(Sentimiento.objects.exists())
        self.assertEqual(Publicacion.objects.count(), 1)
        self.assertEqual(ProcesamientoIAMultifuente.objects.get().estado, 'ERROR')
        self.procesar(recibo)
        self.sdk.models.generate_content.assert_called_once()

    def test_resultados_preexistentes_y_recibos_antiguos_no_se_procesan(self):
        for tipo in ('sentimiento', 'locacion', 'procesado', 'antigua', 'registro_ajeno', 'hash_ajeno'):
            rss = replace(self.noticia, url='https://misionesonline.net/' + tipo)
            recibo = persistir_lote([rss])
            pub = Publicacion.objects.get(pk=recibo['noticias'][0]['publicacion_id'])
            if tipo == 'sentimiento':
                Sentimiento.objects.create(id_publicacion_api=pub, polaridad=-0.8, confianza=0.5)
            elif tipo == 'locacion':
                Locacion.objects.create(id_publicacion_api=pub, location='Posadas', latitud=-27, longitud=-55)
            elif tipo == 'procesado':
                Publicacion.objects.filter(pk=pub.pk).update(procesado_ia=True)
            elif tipo == 'antigua':
                Publicacion.objects.filter(pk=pub.pk).update(fecha_captura=timezone.now() - timedelta(days=2))
                # Histórico sin inscripción original en la cola: nunca descubrirlo.
                ProcesamientoIAMultifuente.objects.filter(publicacion=pub).delete()
            elif tipo == 'registro_ajeno':
                recibo['registro_id'] += 999
            else:
                recibo['noticias'][0]['hash_origen'] = '0' * 64
            self.assertEqual(self.procesar(recibo)['llamadas'], 0)
        self.sdk.models.generate_content.assert_not_called()
        self.assertEqual(ProcesamientoIAMultifuente.objects.exclude(estado='PENDIENTE').count(), 0)
        self.assertEqual(Sentimiento.objects.get().polaridad, -0.8)

    def test_edicion_durante_llamada_no_se_sobrescribe(self):
        recibo = self.guardar()
        def editar(**kwargs):
            Publicacion.objects.update(titulo='Edición humana')
            return SimpleNamespace(text=json.dumps(self.data))
        self.sdk.models.generate_content.side_effect = editar
        self.procesar(recibo)
        self.assertEqual(Publicacion.objects.get().titulo, 'Edición humana')
        self.assertFalse(Sentimiento.objects.exists())
        self.assertEqual(ProcesamientoIAMultifuente.objects.get().codigo_error, 'texto_o_resultados_modificados')

    def test_error_de_una_llamada_no_impide_el_resto_del_lote(self):
        recibo = persistir_lote([self.noticia, replace(self.noticia, url='https://misionesonline.net/segunda')])
        self.sdk.models.generate_content.side_effect = [TimeoutError('fallo'), SimpleNamespace(text=json.dumps(self.data))]
        resultado = self.procesar(recibo)
        self.assertEqual((resultado['procesadas'], len(resultado['errores'])), (1, 1))
        self.assertEqual(Publicacion.objects.count(), 2)

    def test_dry_run_sin_escrituras_senales_ni_sdk(self):
        recibo = self.guardar()
        with CaptureQueriesContext(connection) as consultas, patch.object(Publicacion, 'save', side_effect=AssertionError('Sin señales')):
            resultado = self.procesar(recibo, dry_run=True)
        self.assertEqual(resultado['previstas'], 1)
        self.assertEqual(ProcesamientoIAMultifuente.objects.get().estado, 'PENDIENTE')
        for q in consultas:
            self.assertFalse(q['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')))
        self.sdk.models.generate_content.assert_not_called()
        antes = RegistroDatos.objects.count()
        resultado = ia.persistir_y_procesar([replace(self.noticia, url='https://misionesonline.net/dry')], dry_run=True,
                                          cliente=self.cliente, pausa_segundos=0)
        self.assertEqual(resultado['ingesta']['previstos'], 1)
        self.assertEqual(RegistroDatos.objects.count(), antes)
        self.assertEqual(ProcesamientoIAMultifuente.objects.get().estado, 'PENDIENTE')

    def test_limite_timeout_y_pausa_configurables(self):
        recibo = persistir_lote([replace(self.noticia, url=f'https://misionesonline.net/n{i}') for i in range(3)])
        with patch.object(ia.time, 'sleep') as dormir:
            resultado = ia.procesar_nuevas(recibo, cliente=self.cliente, batch_size=2, timeout_segundos=4, pausa_segundos=12)
        self.assertEqual(resultado['llamadas'], 2)
        dormir.assert_called_once_with(12)
        self.assertEqual(self.sdk.models.generate_content.call_args.kwargs['config'].http_options.timeout, 4000)
        self.assertEqual(self.procesar(recibo)['procesadas'], 1)
        self.assertEqual(self.sdk.models.generate_content.call_count, 3)

    def test_servicio_no_disponible_no_reserva_y_permite_reintento_sin_consumo(self):
        recibo = self.guardar()
        cliente = SimpleNamespace(client=None, types=None)
        resultado = ia.procesar_nuevas(recibo, cliente=cliente)
        self.assertEqual(resultado['errores'][0]['codigo'], 'servicio_no_disponible')
        self.assertEqual(ProcesamientoIAMultifuente.objects.get().estado, 'PENDIENTE')
        self.assertEqual(self.procesar(recibo)['procesadas'], 1)

    def test_reserva_incierta_existente_nunca_reenvia(self):
        recibo = self.guardar()
        pub = Publicacion.objects.get()
        from uuid import uuid4
        ProcesamientoIAMultifuente.objects.filter(publicacion=pub).update(
            estado='EN_PROCESO', enviado=timezone.now(), token_intento=uuid4(), huella_texto=ia._huella(pub))
        self.assertEqual(self.procesar(recibo)['llamadas'], 0)
        self.sdk.models.generate_content.assert_not_called()

    def test_worker_global_reutiliza_reserva_h32(self):
        recibo = self.guardar()
        cliente = GeminiCliente()
        cliente.client, cliente.types, cliente.model_name = self.sdk, types, self.cliente.model_name
        self.sdk.models.generate_content.side_effect = TimeoutError('Incierto')
        with patch('core.services.gemini_cliente.time.sleep'):
            cliente.procesar_pendientes()
        self.procesar(recibo)
        self.sdk.models.generate_content.assert_called_once()


    def test_parametros_invalidos_no_persisten_ni_llaman(self):
        for opciones in ({'batch_size': 0}, {'batch_size': 21}, {'timeout_segundos': 0},
                         {'timeout_segundos': float('inf')}, {'pausa_segundos': -1}, {'dry_run': 'true'}):
            with self.subTest(opciones=opciones), self.assertRaises(ValueError):
                ia.persistir_y_procesar([self.noticia], cliente=self.cliente, **opciones)
        self.assertFalse(Publicacion.objects.exists())
        self.assertFalse(RegistroDatos.objects.exists())
        self.sdk.models.generate_content.assert_not_called()


    def test_competidor_sin_token_no_invalida_respuesta_del_propietario(self):
        from django.db import OperationalError
        recibo = self.guardar()
        def competir(**kwargs):
            token = ProcesamientoIAMultifuente.objects.get().token_intento
            with patch.object(ia, '_reservar', side_effect=OperationalError('Lock timeout del competidor')):
                segundo = self.procesar(recibo)
            self.assertEqual(segundo['llamadas'], 0)
            actual = ProcesamientoIAMultifuente.objects.get()
            self.assertEqual(actual.estado, 'EN_PROCESO')
            self.assertEqual(actual.token_intento, token)
            return SimpleNamespace(text=json.dumps(self.data))
        self.sdk.models.generate_content.side_effect = competir
        primero = self.procesar(recibo)
        self.assertEqual(primero['procesadas'], 1)
        self.assertEqual(ProcesamientoIAMultifuente.objects.get().estado, 'COMPLETADO')
        self.sdk.models.generate_content.assert_called_once()

    def test_token_ajeno_no_marca_error_ni_consume_resultados(self):
        from uuid import uuid4
        recibo = self.guardar()
        pub, token = ia._reservar(Publicacion.objects.get().pk, recibo['registro_id'],
                                  recibo['noticias'][0]['hash_origen'])
        self.assertTrue(ia._marcar_envio(pub.pk, token))
        self.assertEqual(ia._error(pub.pk, uuid4(), 'error_ajeno'), 0)
        self.assertFalse(ia._guardar_resultado(pub, uuid4(), self.data))
        self.assertTrue(ia._guardar_resultado(pub, token, self.data))

    def test_reserva_sin_envio_es_recuperable_y_token_anterior_no_envia(self):
        recibo = self.guardar()
        pub = Publicacion.objects.get()
        _, token_anterior = ia._reservar(pub.pk, recibo['registro_id'], pub.hash_origen)
        # Simula caída antes de la marca de envío. Otro intento invalida el token.
        self.assertEqual(self.procesar(recibo)['procesadas'], 1)
        self.assertFalse(ia._marcar_envio(pub.pk, token_anterior))
        self.assertEqual(ia._error(pub.pk, token_anterior, 'error_tardio'), 0)
        self.sdk.models.generate_content.assert_called_once()

    def test_cinco_reservas_fallidas_no_bloquean_el_territorio(self):
        recibo = persistir_lote([replace(self.noticia, url=f'https://misionesonline.net/error{i}') for i in range(5)])
        for i, item in enumerate(recibo['noticias']):
            ProcesamientoIAMultifuente.objects.filter(publicacion_id=item['publicacion_id']).update(
                estado=('ERROR', 'INCIERTO', 'EN_PROCESO', 'ERROR', 'INCIERTO')[i], enviado=timezone.now())
        territorio = Publicacion.objects.create(hash_origen='territorio-detras', fuente='El Territorio',
                                                titulo='Territorio pendiente', contenido=self.noticia.contenido_completo)
        cliente = GeminiCliente()
        cliente.client, cliente.types, cliente.model_name = self.sdk, types, 'modelo-configurado'
        with patch('core.services.gemini_cliente.time.sleep'):
            resultado = cliente.procesar_pendientes(batch_size=5)
        self.assertEqual(resultado['seleccionadas'], 1)
        self.assertEqual(resultado['procesadas'], 1)
        territorio.refresh_from_db()
        self.assertTrue(territorio.procesado_ia)
        self.sdk.models.generate_content.assert_called_once()

    def test_seis_altas_limite_cinco_no_caducan_y_se_recuperan_sin_recibo(self):
        noticias = [replace(self.noticia, url=f'https://misionesonline.net/seis{i}') for i in range(6)]
        primera = ia.persistir_y_procesar(noticias, cliente=self.cliente, pausa_segundos=0)
        self.assertEqual(primera['ia']['procesadas'], 5)
        self.assertEqual(ProcesamientoIAMultifuente.objects.filter(estado='PENDIENTE').count(), 1)
        with patch.object(ia.timezone, 'now', return_value=timezone.now() + timedelta(days=2)):
            recuperada = ia.procesar_pendientes_multifuente(cliente=self.cliente, pausa_segundos=0)
        self.assertEqual(recuperada['procesadas'], 1)
        self.assertEqual(ProcesamientoIAMultifuente.objects.filter(estado='COMPLETADO').count(), 6)
        self.assertEqual(self.sdk.models.generate_content.call_count, 6)

    def test_reintento_orquestador_con_duplicados_recupera_solo_pendientes_originales(self):
        noticias = [replace(self.noticia, url=f'https://misionesonline.net/reintento{i}') for i in range(6)]
        ia.persistir_y_procesar(noticias, cliente=self.cliente, pausa_segundos=0)
        with patch.object(ia.timezone, 'now', return_value=timezone.now() + timedelta(days=2)):
            segunda = ia.persistir_y_procesar(noticias, cliente=self.cliente, pausa_segundos=0)
        self.assertEqual(segunda['ingesta']['capturados'], 0)
        self.assertEqual(segunda['ia']['procesadas'], 1)
        self.assertEqual(self.sdk.models.generate_content.call_count, 6)

    def test_cola_se_crea_en_commit_de_h31_y_no_se_descubren_historicos(self):
        recibo = self.guardar()
        self.assertEqual(ProcesamientoIAMultifuente.objects.get().estado, 'PENDIENTE')
        historica = Publicacion.objects.create(hash_origen='sin-cola-historica', fuente=self.noticia.fuente,
                                               titulo=self.noticia.titulo, contenido=self.noticia.contenido_completo,
                                               url='https://misionesonline.net/historica',
                                               id_registro_id=recibo['registro_id'])
        with CaptureQueriesContext(connection) as consultas:
            previsto = ia.procesar_pendientes_multifuente(dry_run=True, cliente=self.cliente, pausa_segundos=0)
        self.assertEqual(previsto['previstas'], 1)
        for consulta in consultas:
            self.assertFalse(consulta['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')))
        self.assertFalse(ProcesamientoIAMultifuente.objects.filter(publicacion=historica).exists())
        self.sdk.models.generate_content.assert_not_called()

    def test_fallo_cola_revierte_alta_y_relaciones(self):
        with patch.object(ProcesamientoIAMultifuente.objects, 'create', side_effect=RuntimeError('Fallo de cola')):
            resultado = persistir_lote([self.noticia])
        self.assertEqual(len(resultado['errores']), 1)
        for modelo in (Publicacion, AliasURLPublicacion, PublicacionTema, PublicacionEtiqueta, ProcesamientoIAMultifuente):
            self.assertFalse(modelo.objects.exists())


@skipUnless(connection.vendor == 'postgresql', 'Requiere PostgreSQL efímero')
class ConcurrenciaGeminiMultifuenteTests(TransactionTestCase):
    def setUp(self):
        f = FUENTES_RSS[0]
        noticia = NoticiaRSS(f.nombre, f.identificador, 'Nueva propuesta educativa',
                            'https://misionesonline.net/concurrente', None, '',
                            'La comunidad presentó una propuesta educativa para mejorar las escuelas '
                            'de la ciudad y ampliar las actividades destinadas a estudiantes y familias '
                            'durante todo el próximo año escolar.', '')
        self.recibo = persistir_lote([noticia])
        self.sdk = Mock()
        self.data = dict(polaridad=0.3, confianza=0.8, localidades=[])
        self.cliente = SimpleNamespace(client=self.sdk, types=types, model_name='modelo-configurado')
        self.llamadas = []
        def generar(**kwargs):
            self.assertFalse(connection.in_atomic_block)
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='advisory'")
                self.assertEqual(cursor.fetchone()[0], 0)
            self.llamadas.append(kwargs)
            return SimpleNamespace(text=json.dumps(self.data))
        self.sdk.models.generate_content.side_effect = generar

    def competir(self, incluir_global=False):
        barrera = Barrier(2)
        original = ia._reservar
        def reservar(*args):
            barrera.wait(timeout=15)
            return original(*args)
        def ejecutar(global_):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid()')
                    pid = cursor.fetchone()[0]
                    cursor.execute("SET lock_timeout = '10s'")
                if global_:
                    cliente = GeminiCliente()
                    cliente.client, cliente.types, cliente.model_name = self.sdk, types, self.cliente.model_name
                    resultado = cliente.procesar_pendientes()
                else:
                    resultado = ia.procesar_nuevas(self.recibo, cliente=self.cliente, pausa_segundos=0)
                return pid, resultado
            finally:
                connections.close_all()
        with patch.object(ia, '_reservar', side_effect=reservar), patch.object(ia.time, 'sleep'):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futuros = [pool.submit(ejecutar, False), pool.submit(ejecutar, incluir_global)]
                resultados = [f.result(timeout=30) for f in futuros]
        self.assertEqual(len({pid for pid, _ in resultados}), 2)
        return [r for _, r in resultados]

    def test_dos_procesadores_mismo_recibo_una_sola_llamada(self):
        resultados = self.competir()
        self.assertEqual(sum(r['procesadas'] for r in resultados), 1)
        self.assertEqual(sum(r['omitidas'] for r in resultados), 1)
        self.assertEqual(len(self.llamadas), 1)
        self.assertEqual(ProcesamientoIAMultifuente.objects.count(), 1)
        self.assertEqual(Sentimiento.objects.count(), 1)
        ia.procesar_nuevas(self.recibo, cliente=self.cliente, pausa_segundos=0)
        self.assertEqual(len(self.llamadas), 1)

    def test_worker_global_y_selectivo_comparten_reserva(self):
        resultados = self.competir(incluir_global=True)
        self.assertEqual(sum(r['procesadas'] for r in resultados), 1)
        self.assertEqual(len(self.llamadas), 1)
        self.assertEqual(Sentimiento.objects.count(), 1)

    def test_fallo_concurrente_no_habilita_otro_envio(self):
        self.sdk.models.generate_content.side_effect = TimeoutError('Resultado desconocido')
        self.competir()
        self.assertEqual(self.sdk.models.generate_content.call_count, 1)
        self.assertEqual(ProcesamientoIAMultifuente.objects.get().estado, 'INCIERTO')
        self.assertFalse(Sentimiento.objects.exists())
        ia.procesar_nuevas(self.recibo, cliente=self.cliente, pausa_segundos=0)
        self.assertEqual(self.sdk.models.generate_content.call_count, 1)


    def test_competidor_con_lock_timeout_real_no_invalida_al_propietario(self):
        en_vuelo, liberar = Event(), Event()
        original = self.sdk.models.generate_content.side_effect
        def generar(**kwargs):
            en_vuelo.set()
            if not liberar.wait(timeout=15):
                raise AssertionError('No se liberó la llamada simulada')
            return original(**kwargs)
        self.sdk.models.generate_content.side_effect = generar
        def ejecutar():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '250ms'")
                return ia.procesar_nuevas(self.recibo, cliente=self.cliente, pausa_segundos=0)
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            propietario = pool.submit(ejecutar)
            try:
                self.assertTrue(en_vuelo.wait(timeout=10))
                token = ProcesamientoIAMultifuente.objects.get().token_intento
                with transaction.atomic():
                    Publicacion.objects.select_for_update().get()
                    competidor = pool.submit(ejecutar).result(timeout=5)
                    self.assertEqual(competidor['llamadas'], 0)
                    self.assertEqual(competidor['errores'][0]['codigo'], 'persistencia_ia')
                    reserva = ProcesamientoIAMultifuente.objects.get()
                    self.assertEqual(reserva.token_intento, token)
                    self.assertEqual(reserva.estado, 'EN_PROCESO')
            finally:
                liberar.set()
            resultado = propietario.result(timeout=10)
        self.assertEqual(resultado['procesadas'], 1)
        self.assertEqual(ProcesamientoIAMultifuente.objects.get().estado, 'COMPLETADO')
        self.assertEqual(self.sdk.models.generate_content.call_count, 1)


    def test_envio_entre_consulta_y_bloqueo_no_permite_robar_token(self):
        pk = self.recibo['noticias'][0]['publicacion_id']
        pub = Publicacion.objects.get(pk=pk)
        propietario, token = ia._reservar(pk, self.recibo['registro_id'], pub.hash_origen)
        consultado, continuar = Event(), Event()
        original = ia._elegible
        def consultar(*args):
            elegible = original(*args)
            self.assertTrue(elegible)
            consultado.set()
            if not continuar.wait(timeout=10):
                raise AssertionError('No se liberó el competidor')
            return elegible
        def competir():
            close_old_connections()
            try:
                return ia._reservar(pk, self.recibo['registro_id'], pub.hash_origen)
            finally:
                connections.close_all()
        with patch.object(ia, '_elegible', side_effect=consultar):
            with ThreadPoolExecutor(max_workers=1) as pool:
                futuro = pool.submit(competir)
                try:
                    self.assertTrue(consultado.wait(timeout=10))
                    self.assertTrue(ia._marcar_envio(pk, token))
                finally:
                    continuar.set()
                self.assertIsNone(futuro.result(timeout=10))
        self.assertEqual(ProcesamientoIAMultifuente.objects.get().token_intento, token)
        self.assertTrue(ia._guardar_resultado(propietario, token, self.data))
        self.assertEqual(ProcesamientoIAMultifuente.objects.get().estado, 'COMPLETADO')


class MigracionGeminiMultifuenteTests(SimpleTestCase):
    def test_reserva_unica_aditiva_sin_cambios_de_datos(self):
        import importlib
        from django.db import migrations, models
        migration = importlib.import_module('core.migrations.0021_procesamientoiamultifuente').Migration
        self.assertEqual(migration.dependencies, [('core', '0020_aliasurlpublicacion')])
        self.assertEqual(len(migration.operations), 1)
        operacion = migration.operations[0]
        self.assertIsInstance(operacion, migrations.CreateModel)
        self.assertEqual(operacion.name, 'ProcesamientoIAMultifuente')
        publicacion = dict(operacion.fields)['publicacion']
        self.assertIsInstance(publicacion, models.OneToOneField)
        self.assertTrue(publicacion.primary_key)


class AutorizacionGeminiMultifuenteTests(GeminiMultifuenteTests):
    def test_fuente_editorial_catalogada_no_pasa_a_legacy_con_registro_ausente_o_inconsistente(self):
        recibo = self.guardar()
        pub_id = recibo['noticias'][0]['publicacion_id']
        with override_settings(GEMINI_MULTIFUENTE_FUENTES_AUTORIZADAS=(self.noticia.fuente_id,)):
            pub = Publicacion.objects.get(pk=pub_id)
            RegistroDatos.objects.filter(pk=pub.id_registro_id).update(fuentes_api='otro-origen')
            cliente = GeminiCliente()
            cliente.client, cliente.types = self.sdk, types
            self.assertEqual(cliente.procesar_pendientes()['seleccionadas'], 0)
            pub.id_registro = None
            pub.save(update_fields=['id_registro'])
            self.assertEqual(cliente.procesar_pendientes()['seleccionadas'], 0)
        self.sdk.models.generate_content.assert_not_called()
        self.assertEqual(ProcesamientoIAMultifuente.objects.get(publicacion_id=pub_id).estado, 'PENDIENTE')

    def test_denegada_por_defecto_y_recuperable_sin_consumir_cupo(self):
        from django.test import override_settings
        recibo = self.guardar()
        pub_id = recibo['noticias'][0]['publicacion_id']
        with override_settings(GEMINI_MULTIFUENTE_FUENTES_AUTORIZADAS=()):
            globales = Publicacion.objects.filter(ia.filtro_cliente_global(), procesado_ia=False)
            self.assertFalse(globales.filter(pk=pub_id).exists())
            cliente_global = GeminiCliente()
            cliente_global.client, cliente_global.types = self.sdk, types
            self.assertEqual(cliente_global.procesar_pendientes()['seleccionadas'], 0)
            self.sdk.models.generate_content.assert_not_called()
            resultado = self.procesar(recibo, batch_size=1)
            self.assertEqual(resultado['llamadas'], 0)
            self.sdk.models.generate_content.assert_not_called()
            trabajo = ProcesamientoIAMultifuente.objects.get(publicacion_id=pub_id)
            self.assertEqual(trabajo.estado, 'PENDIENTE')
            self.assertIsNone(trabajo.token_intento)

    def test_autorizacion_revalidada_inmediatamente_antes_del_envio(self):
        from django.test import override_settings
        recibo = self.guardar()
        with override_settings(GEMINI_MULTIFUENTE_FUENTES_AUTORIZADAS=(self.noticia.fuente_id,)):
            with patch.object(ia, '_marcar_envio', side_effect=lambda *args: False):
                # La revocación entre reserva y envío deja la fila recuperable.
                with patch.object(ia, 'publicacion_multifuente_autorizada', side_effect=[True, False]):
                    resultado = self.procesar(recibo)
        self.assertEqual(resultado['llamadas'], 0)
        self.sdk.models.generate_content.assert_not_called()
        trabajo = ProcesamientoIAMultifuente.objects.get()
        self.assertEqual(trabajo.estado, 'PENDIENTE')
        self.assertIsNone(trabajo.token_intento)

    def test_fuente_autorizada_procesa_y_ids_invalidos_fallan_cerrado(self):
        from django.test import override_settings
        from django.core.exceptions import ImproperlyConfigured
        recibo = self.guardar()
        with override_settings(GEMINI_MULTIFUENTE_FUENTES_AUTORIZADAS=(self.noticia.fuente_id,)):
            resultado = self.procesar(recibo)
        self.assertEqual(resultado['llamadas'], 1)
        self.sdk.models.generate_content.assert_called_once()
        with override_settings(GEMINI_MULTIFUENTE_FUENTES_AUTORIZADAS=('fuente_ajena',)):
            with self.assertRaises(ImproperlyConfigured):
                ia.filtro_cliente_global()
