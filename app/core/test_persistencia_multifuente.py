"""H3.1: ORM real sobre la base efímera del test runner, sin red ni Gemini."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from unittest import skipUnless
from datetime import datetime, timezone as tz
from unittest.mock import patch

from django.db import close_old_connections, connection, connections, transaction
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext

from core.models import (AliasURLPublicacion, Categoria, Etiqueta, Publicacion, PublicacionEtiqueta,
                         PublicacionTema, RegistroDatos, Tema)
from core.services import persistencia_multifuente as servicio
from core.services.extractor_articulos import ArticuloExtraido
from core.services.fuentes_rss import FUENTES_RSS
from core.services.lector_rss import NoticiaRSS


class PersistenciaMultifuenteTests(TestCase):
    def setUp(self):
        self.fuente = FUENTES_RSS[0]
        self.texto = ('El hospital de San Pedro anunció nuevas jornadas de vacunación y atención médica '
                      'para las familias de la localidad. Los médicos atenderán consultas de salud '
                      'durante toda la semana y ofrecerán controles gratuitos a los vecinos.')
        self.noticia = NoticiaRSS(self.fuente.nombre, self.fuente.identificador,
                                 'Hospital de San Pedro anuncia vacunación',
                                 'https://misionesonline.net/nota?id=7&utm_source=rss',
                                 datetime(2026, 11, 5, 12, tzinfo=tz.utc),
                                 'Resumen breve, no es el cuerpo.', self.texto, 'salud')
        for destino in ('socket.getaddrinfo', 'socket.socket.connect', 'socket.socket.connect_ex',
                        'urllib.request.urlopen', 'core.services.descarga_segura.descargar',
                        'core.services.clasificacion._clasificar_con_ia'):
            parche = patch(destino, side_effect=AssertionError('Sin red ni Gemini'))
            parche.start()
            self.addCleanup(parche.stop)

    def test_guarda_publicacion_auditoria_clasificacion_y_etiquetas(self):
        resultado = servicio.persistir_lote([self.noticia])
        self.assertEqual(resultado['capturados'], 1)
        self.assertEqual(resultado['errores'], [])
        publicacion = Publicacion.objects.get()
        self.assertEqual(publicacion.url, 'https://misionesonline.net/nota?id=7')
        self.assertEqual(publicacion.contenido, self.texto)
        self.assertEqual(publicacion.fecha_publicacion, self.noticia.fecha)
        self.assertEqual(publicacion.departamento, 'sanpedro')
        self.assertFalse(publicacion.procesado_ia)
        self.assertEqual(publicacion.id_registro_id, resultado['registro_id'])
        self.assertEqual(RegistroDatos.objects.get().estado, 'EXITO')
        self.assertTrue(PublicacionEtiqueta.objects.filter(publicacion=publicacion).exists())
        self.assertTrue(PublicacionTema.objects.filter(id_publicacion_api=publicacion).exists())

    def test_mismo_hecho_en_otro_medio_se_conserva(self):
        otra = FUENTES_RSS[1]
        noticia = replace(self.noticia, fuente=otra.nombre, fuente_id=otra.identificador,
                          url='https://' + otra.hosts_permitidos[0] + '/nota?id=7')
        resultado = servicio.persistir_lote([self.noticia, noticia])
        self.assertEqual(resultado['capturados'], 2)
        self.assertEqual(Publicacion.objects.values('hash_origen').distinct().count(), 2)
        self.assertEqual(set(Publicacion.objects.values_list('fuente', flat=True)), {otra.nombre, self.fuente.nombre})

    def test_reintentos_y_variantes_de_tracking_son_idempotentes(self):
        variantes = [self.noticia, replace(self.noticia, url='HTTPS://MISIONESONLINE.NET:443/nota?id=7&fbclid=abc')]
        resultado = servicio.persistir_lote(variantes)
        self.assertEqual((resultado['capturados'], resultado['omitidas']), (1, 1))
        publicacion = Publicacion.objects.get()
        pk, hash_original = publicacion.pk, publicacion.hash_origen
        resultado = servicio.persistir_lote(variantes)
        self.assertEqual((resultado['capturados'], resultado['omitidas']), (0, 2))
        self.assertEqual(Publicacion.objects.get().pk, pk)
        self.assertEqual(Publicacion.objects.get().hash_origen, hash_original)
        self.assertEqual(RegistroDatos.objects.count(), 2)  # Auditoría por ejecución.

    def test_query_funcional_ruta_www_y_barras_no_se_fusionan(self):
        urls = ('https://misionesonline.net/nota?id=7', 'https://misionesonline.net/nota?id=8',
                'https://misionesonline.net/nota/?id=7', 'https://www.misionesonline.net/nota?id=7',
                'https://misionesonline.net/Nota?id=7')
        resultado = servicio.persistir_lote([replace(self.noticia, url=url) for url in urls])
        self.assertEqual(resultado['capturados'], 5)

    def test_compatibilidad_18_fuentes(self):
        noticias = [replace(self.noticia, fuente=f.nombre, fuente_id=f.identificador,
                            url='https://' + f.hosts_permitidos[0] + '/nota') for f in FUENTES_RSS]
        resultado = servicio.persistir_lote(noticias)
        self.assertEqual(resultado['errores'], [])
        self.assertEqual(resultado['capturados'], 18)

    def test_hash_historico_y_pk_no_se_recalculan(self):
        registro = RegistroDatos.objects.create(fuentes_api=self.fuente.nombre,
                                               fecha_ejecucion=self.noticia.fecha,
                                               estado='EXITO', lenguaje='es')
        historica = Publicacion.objects.create(hash_origen='hash-historico-arbitrario', fuente=self.fuente.nombre,
                                              titulo=self.noticia.titulo, contenido=self.texto,
                                              url='https://misionesonline.net/nota?id=7&utm_medium=feed',
                                              id_registro=registro)
        antes = Publicacion.objects.filter(pk=historica.pk).values().get()
        resultado = servicio.persistir_lote([self.noticia])
        self.assertEqual(resultado['omitidas'], 1)
        self.assertEqual(Publicacion.objects.filter(pk=historica.pk).values().get(), antes)

    def test_territorio_historico_permanece_intacto(self):
        historica = Publicacion.objects.create(hash_origen='territorio-historico', fuente='El Territorio',
                                              titulo=self.noticia.titulo, contenido=self.texto,
                                              url='https://www.elterritorio.com.ar/nota')
        antes = Publicacion.objects.filter(pk=historica.pk).values().get()
        servicio.persistir_lote([self.noticia])
        self.assertEqual(Publicacion.objects.filter(pk=historica.pk).values().get(), antes)
        self.assertEqual(Publicacion.objects.count(), 2)

    def test_articulo_h23_y_pareja_rss_html(self):
        articulo = ArticuloExtraido(self.fuente.nombre, self.fuente.identificador,
                                   'Título extraído', self.texto, 'https://misionesonline.net/foto.jpg',
                                   self.noticia.fecha, 'https://misionesonline.net/canonica', True)
        entrada = servicio.EntradaPersistencia(self.noticia, articulo)
        resultado = servicio.persistir_lote([entrada, self.noticia, articulo])
        self.assertEqual((resultado['capturados'], resultado['omitidas']), (1, 2))
        publicacion = Publicacion.objects.get()
        self.assertEqual(publicacion.titulo, articulo.titulo)
        self.assertEqual(publicacion.url, articulo.url_canonica)
        self.assertEqual(publicacion.imagen_url, articulo.imagen_principal)
        # La identidad RSS sigue estable aunque cambie la canónica en un reintento.
        reintento = replace(entrada, articulo=replace(articulo, url_canonica='https://misionesonline.net/nueva-canonica'))
        self.assertEqual(servicio.persistir_lote([reintento])['omitidas'], 1)
        self.assertEqual(Publicacion.objects.get().url, articulo.url_canonica)

    def test_rechaza_titulos_fechas_urls_y_contenido_invalidos_por_noticia(self):
        casos = [replace(self.noticia, titulo=t) for t in ('', '   ', 'x' * 256, 'Texto\x00inválido')]
        casos += [replace(self.noticia, fecha=f) for f in ('ayer', datetime(2026, 11, 5))]
        casos += [replace(self.noticia, url=u) for u in (
            'http://misionesonline.net/nota', 'https://primeraedicion.com.ar/nota',
            'https://127.0.0.1/', 'https://misionesonline.net/nota#fragmento',
            'https://user@misionesonline.net/nota', 'https://misionesonline.net/' + 'a' * 500)]
        casos += [replace(self.noticia, contenido_completo=c) for c in (
            '', 'Sólo un resumen.', 'x' * 130, self.texto + '\x00', self.texto * 10000)]
        casos += [replace(self.noticia, fuente='Otro nombre'), replace(self.noticia, fuente_id='desconocida'),
                  None, {'titulo': 'No normalizada'}]
        resultado = servicio.persistir_lote(casos + [self.noticia])
        self.assertEqual(len(resultado['errores']), len(casos))
        self.assertEqual(resultado['capturados'], 1)
        self.assertEqual(resultado['estado'], 'PARCIAL')
        self.assertEqual(RegistroDatos.objects.get().estado, 'ERROR: PARCIAL')

    def test_no_guarda_resumen_como_cuerpo_y_no_inventa_fecha(self):
        parcial = replace(self.noticia, contenido_completo='', resumen=self.texto)
        resultado = servicio.persistir_lote([parcial, replace(self.noticia, fecha=None)])
        self.assertEqual(len(resultado['errores']), 1)
        self.assertIsNone(Publicacion.objects.get().fecha_publicacion)

    def test_articulo_insuficiente_o_imagen_invalida_no_se_persisten(self):
        articulo = ArticuloExtraido(self.fuente.nombre, self.fuente.identificador,
                                   self.noticia.titulo, self.texto, '', self.noticia.fecha,
                                   'https://misionesonline.net/nota', True)
        invalidos = [replace(articulo, suficiente=False), replace(articulo, cuerpo='Breve.')]
        invalidos += [replace(articulo, imagen_principal=url) for url in (
            'https://evil.org/foto', 'http://misionesonline.net/foto',
            'data:image/png;base64,abc', 'https://misionesonline.net/' + 'x' * 501)]
        resultado = servicio.persistir_lote(invalidos)
        self.assertEqual(len(resultado['errores']), len(invalidos))
        self.assertFalse(Publicacion.objects.exists())

    def test_pareja_de_medios_distintos_se_rechaza(self):
        otra = FUENTES_RSS[1]
        articulo = ArticuloExtraido(otra.nombre, otra.identificador, self.noticia.titulo, self.texto,
                                   '', self.noticia.fecha, 'https://' + otra.hosts_permitidos[0] + '/nota', True)
        resultado = servicio.persistir_lote([servicio.EntradaPersistencia(self.noticia, articulo)])
        self.assertEqual(len(resultado['errores']), 1)
        self.assertFalse(Publicacion.objects.exists())

    def test_dry_run_no_ejecuta_sql_de_escritura(self):
        with CaptureQueriesContext(connection) as consultas:
            resultado = servicio.persistir_lote([self.noticia, self.noticia,
                                                 replace(self.noticia, titulo='')], dry_run=True)
        self.assertEqual((resultado['previstos'], resultado['omitidas'], resultado['capturados']), (1, 1, 0))
        self.assertIsNone(resultado['registro_id'])
        self.assertTrue(resultado['noticias'][0]['etiquetas'])
        for consulta in consultas:
            self.assertFalse(consulta['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'REPLACE')))
        for modelo in (AliasURLPublicacion, Publicacion, RegistroDatos, Categoria, Tema, Etiqueta, PublicacionEtiqueta, PublicacionTema):
            self.assertEqual(modelo.objects.count(), 0)
        real = servicio.persistir_lote([self.noticia])
        self.assertEqual(real['noticias'][0]['hash_origen'], resultado['noticias'][0]['hash_origen'])

    def test_dry_run_detecta_existente_sin_modificar_auditoria(self):
        servicio.persistir_lote([self.noticia])
        with CaptureQueriesContext(connection) as consultas:
            resultado = servicio.persistir_lote([self.noticia], dry_run=True)
        self.assertEqual(resultado['omitidas'], 1)
        self.assertEqual(RegistroDatos.objects.count(), 1)
        for consulta in consultas:
            self.assertFalse(consulta['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')))

    def test_fallo_de_etiquetas_revierte_noticia_y_continua_lote(self):
        from core.signals_etiquetas import sincronizar_etiquetas
        def sincronizar(publicacion, **kwargs):
            sincronizar_etiquetas(publicacion, **kwargs)
            if publicacion.titulo.startswith('Fallará'):
                raise RuntimeError('Fallo simulado después de generar etiquetas')
        with patch('core.signals_etiquetas.sincronizar_etiquetas', side_effect=sincronizar):
            resultado = servicio.persistir_lote([replace(self.noticia, titulo='Fallará EtiquetaFantasma',
                                                         url='https://misionesonline.net/falla'), self.noticia])
        self.assertEqual((resultado['capturados'], len(resultado['errores'])), (1, 1))
        self.assertEqual(Publicacion.objects.get().titulo, self.noticia.titulo)
        self.assertFalse(Etiqueta.objects.filter(slug='etiquetafantasma').exists())

    def test_fallo_de_categoria_revierte_todas_las_relaciones_y_permite_reintento(self):
        original = servicio.vincular_categoria_por_nombre
        def vincular(publicacion, nombre):
            original(publicacion, nombre)
            raise RuntimeError('Fallo simulado después de vincular categoría')
        with patch.object(servicio, 'vincular_categoria_por_nombre', side_effect=vincular):
            resultado = servicio.persistir_lote([self.noticia])
        self.assertEqual(len(resultado['errores']), 1)
        for modelo in (AliasURLPublicacion, Publicacion, Etiqueta, Categoria, Tema, PublicacionTema, PublicacionEtiqueta):
            self.assertFalse(modelo.objects.exists())
        self.assertEqual(servicio.persistir_lote([self.noticia])['capturados'], 1)

    def test_unique_real_resuelve_carrera_sin_duplicar(self):
        servicio.persistir_lote([self.noticia])
        original = servicio._existente
        llamadas = 0
        def consulta(*args):
            nonlocal llamadas
            llamadas += 1
            # Simula la lectura anterior al commit de otro escritor.
            return None if llamadas == 1 else original(*args)
        with patch.object(servicio, '_existente', side_effect=consulta):
            resultado = servicio.persistir_lote([self.noticia])
        self.assertEqual((resultado['capturados'], resultado['omitidas']), (0, 1))
        self.assertEqual(resultado['errores'], [])
        self.assertEqual(Publicacion.objects.count(), 1)

    def test_clasificacion_fallida_aislada_y_no_confirmada_sin_asociacion(self):
        real = servicio.clasificar_lote
        def clasificar(noticias, **kwargs):
            if noticias[0]['titulo'] == 'Error de clasificación':
                raise RuntimeError('Fallo de reglas')
            return real(noticias, **kwargs)
        with patch.object(servicio, 'clasificar_lote', side_effect=clasificar):
            resultado = servicio.persistir_lote([replace(self.noticia, titulo='Error de clasificación'), self.noticia])
        self.assertEqual((resultado['capturados'], len(resultado['errores'])), (1, 1))
        with patch.object(servicio, 'clasificar_lote', return_value=[dict(categoria='Sociedad', departamento='', confirmada=False)]):
            resultado = servicio.persistir_lote([replace(self.noticia, url='https://misionesonline.net/sin-categoria')])
        pk = resultado['noticias'][0]['publicacion_id']
        self.assertFalse(PublicacionTema.objects.filter(id_publicacion_api_id=pk).exists())


    def test_hash_versionado_estable_y_compatibilidad_del_generador_historico(self):
        import hashlib
        resultado = servicio.persistir_lote([self.noticia])
        esperado = hashlib.sha256(b'["rss:v1","misiones_online","https://misionesonline.net/nota?id=7"]').hexdigest()
        self.assertEqual(resultado['noticias'][0]['hash_origen'], esperado)
        self.assertEqual(servicio.generar_hash(self.noticia.url), hashlib.sha256(self.noticia.url.encode()).hexdigest())

    def test_errores_de_longitud_en_clasificacion_no_dejan_publicacion(self):
        with patch.object(servicio, 'clasificar_lote', return_value=[dict(categoria='Salud', departamento='x' * 31, confirmada=True)]):
            resultado = servicio.persistir_lote([self.noticia])
        self.assertEqual(len(resultado['errores']), 1)
        self.assertFalse(Publicacion.objects.exists())
        self.assertFalse(Etiqueta.objects.exists())

    def test_parametro_dry_run_no_booleano_se_rechaza_sin_auditoria(self):
        for valor in (1, 'true', None):
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                servicio.persistir_lote([self.noticia], dry_run=valor)
        self.assertFalse(RegistroDatos.objects.exists())


    def test_ordenes_rss_y_canonica_persisten_alias_incluso_en_duplicados(self):
        for numero, orden in enumerate((('html', 'pareja', 'rss'), ('rss', 'pareja', 'html'),
                                        ('pareja', 'rss', 'html'), ('pareja', 'html', 'rss'))):
            rss = replace(self.noticia, url=f'https://misionesonline.net/orden{numero}/rss')
            html = ArticuloExtraido(self.fuente.nombre, self.fuente.identificador, rss.titulo,
                                   self.texto, '', rss.fecha, f'https://misionesonline.net/orden{numero}/canonica', True)
            entradas = dict(rss=rss, html=html, pareja=servicio.EntradaPersistencia(rss, html))
            ids = []
            for posicion, tipo in enumerate(orden):
                resultado = servicio.persistir_lote([entradas[tipo]])
                self.assertEqual(resultado['errores'], [])
                self.assertEqual(resultado['capturados'], 1 if posicion == 0 else 0)
                ids.append(resultado['noticias'][0]['publicacion_id'])
            self.assertEqual(len(set(ids)), 1)
            self.assertEqual(AliasURLPublicacion.objects.filter(publicacion_id=ids[0]).count(), 2)
        self.assertEqual(Publicacion.objects.count(), 4)

    def test_alias_nuevo_en_duplicado_no_modifica_publicacion_ni_senales(self):
        primero = servicio.persistir_lote([self.noticia])
        pk = primero['noticias'][0]['publicacion_id']
        antes = Publicacion.objects.filter(pk=pk).values().get()
        html = ArticuloExtraido(self.fuente.nombre, self.fuente.identificador, 'Título nuevo',
                               self.texto, '', None, 'https://misionesonline.net/canonica-nueva', True)
        with patch.object(Publicacion, 'save', side_effect=AssertionError('No modificar histórico')):
            resultado = servicio.persistir_lote([servicio.EntradaPersistencia(self.noticia, html)])
        self.assertEqual(resultado['omitidas'], 1)
        self.assertEqual(Publicacion.objects.filter(pk=pk).values().get(), antes)
        self.assertTrue(AliasURLPublicacion.objects.filter(publicacion_id=pk, url_normalizada=html.url_canonica).exists())

    def test_aliases_incompatibles_no_fusionan_historicos(self):
        a = Publicacion.objects.create(hash_origen='historico-a', fuente=self.fuente.nombre,
                                       url='https://misionesonline.net/duplicada', titulo=self.noticia.titulo,
                                       contenido=self.texto)
        b = Publicacion.objects.create(hash_origen='historico-b', fuente=self.fuente.nombre,
                                       url=a.url + '?utm_source=otro', titulo=a.titulo, contenido=a.contenido)
        antes = list(Publicacion.objects.order_by('pk').values())
        resultado = servicio.persistir_lote([replace(self.noticia, url=a.url), self.noticia])
        self.assertEqual(resultado['errores'][0]['codigo'], 'conflicto_identidad')
        self.assertEqual(resultado['capturados'], 1)
        self.assertEqual(list(Publicacion.objects.filter(pk__in=[a.pk, b.pk]).order_by('pk').values()), antes)
        self.assertFalse(AliasURLPublicacion.objects.filter(publicacion_id__in=[a.pk, b.pk]).exists())

    def test_conflicto_al_vincular_historicos_distintos_revierte_aliases(self):
        primero = servicio.persistir_lote([self.noticia])
        html = ArticuloExtraido(self.fuente.nombre, self.fuente.identificador, self.noticia.titulo,
                               self.texto, '', None, 'https://misionesonline.net/otra-identidad', True)
        segundo = servicio.persistir_lote([html])
        self.assertNotEqual(primero['noticias'][0]['publicacion_id'], segundo['noticias'][0]['publicacion_id'])
        resultado = servicio.persistir_lote([servicio.EntradaPersistencia(self.noticia, html)])
        self.assertEqual(resultado['errores'][0]['codigo'], 'conflicto_identidad')
        self.assertEqual(Publicacion.objects.count(), 2)
        self.assertEqual(AliasURLPublicacion.objects.count(), 2)

    def test_fallo_de_alias_revierte_noticia_y_relaciones(self):
        real = servicio._vincular_aliases
        def fallar(*args):
            real(*args)
            raise RuntimeError('Fallo después de crear alias')
        with patch.object(servicio, '_vincular_aliases', side_effect=fallar):
            resultado = servicio.persistir_lote([self.noticia])
        self.assertEqual(len(resultado['errores']), 1)
        for modelo in (AliasURLPublicacion, Publicacion, Etiqueta, Categoria, Tema, PublicacionTema):
            self.assertFalse(modelo.objects.exists())
        self.assertEqual(servicio.persistir_lote([self.noticia])['capturados'], 1)

    def test_fallo_de_alias_en_duplicado_revierte_solo_alias_nuevo(self):
        servicio.persistir_lote([self.noticia])
        html = ArticuloExtraido(self.fuente.nombre, self.fuente.identificador, self.noticia.titulo,
                               self.texto, '', None, 'https://misionesonline.net/alias-fallido', True)
        real = servicio._vincular_aliases
        def fallar(*args):
            real(*args)
            raise RuntimeError('Fallo después de ampliar alias')
        with patch.object(servicio, '_vincular_aliases', side_effect=fallar):
            resultado = servicio.persistir_lote([servicio.EntradaPersistencia(self.noticia, html)])
        self.assertEqual(len(resultado['errores']), 1)
        self.assertEqual(Publicacion.objects.count(), 1)
        self.assertEqual(AliasURLPublicacion.objects.count(), 1)

    def test_dry_run_simula_aliases_transitivos_sin_escribir(self):
        html = ArticuloExtraido(self.fuente.nombre, self.fuente.identificador, self.noticia.titulo,
                               self.texto, '', None, 'https://misionesonline.net/canonica-dry', True)
        entradas = [html, servicio.EntradaPersistencia(self.noticia, html), self.noticia]
        with CaptureQueriesContext(connection) as consultas, patch.object(
            servicio, '_bloquear_fuente', side_effect=AssertionError('Dry-run no debe bloquear')
        ):
            resultado = servicio.persistir_lote(entradas, dry_run=True)
        self.assertEqual(resultado['errores'], [])
        self.assertEqual((resultado['previstos'], resultado['omitidas']), (1, 2))
        self.assertFalse(AliasURLPublicacion.objects.exists())
        for consulta in consultas:
            self.assertFalse(consulta['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')))
        real = servicio.persistir_lote(entradas)
        self.assertEqual((real['capturados'], real['omitidas']), (1, 2))

    def test_restriccion_unique_de_alias_y_fk(self):
        from django.db import IntegrityError, transaction
        servicio.persistir_lote([self.noticia])
        alias = AliasURLPublicacion.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            AliasURLPublicacion.objects.create(fuente=alias.fuente, url_normalizada=alias.url_normalizada,
                                              publicacion_id=alias.publicacion_id)
        self.assertEqual(AliasURLPublicacion.objects.count(), 1)


@skipUnless(connection.vendor == 'postgresql', 'Concurrencia real requiere PostgreSQL efímero')
class ConcurrenciaPersistenciaMultifuenteTests(TransactionTestCase):
    def setUp(self):
        self.fuente = FUENTES_RSS[0]
        self.texto = ('La comunidad presentó proyectos educativos para mejorar las escuelas de la ciudad '
                      'y ampliar las actividades destinadas a las familias de la región durante el próximo año.')
        self.rss = NoticiaRSS(self.fuente.nombre, self.fuente.identificador, 'Proyectos educativos',
                             'https://misionesonline.net/rss-1', None, '', self.texto, '')
        self.html = ArticuloExtraido(self.fuente.nombre, self.fuente.identificador, self.rss.titulo,
                                    self.texto, '', None, 'https://misionesonline.net/canonica', True)
        for destino in ('core.services.descarga_segura.descargar',
                        'core.services.clasificacion._clasificar_con_ia'):
            parche = patch(destino, side_effect=AssertionError('Sin descargas ni Gemini'))
            parche.start()
            self.addCleanup(parche.stop)

    def ejecutar_concurrentes(self, entradas):
        barrera = Barrier(2)
        original = servicio._bloquear_fuente
        def sincronizar(fuente):
            barrera.wait(timeout=20)
            return original(fuente)
        def escritor(entrada):
            close_old_connections()
            try:
                with connections['default'].cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid()')
                    pid = cursor.fetchone()[0]
                    cursor.execute("SET lock_timeout = '15s'")
                return pid, servicio.persistir_lote([entrada])
            finally:
                connections.close_all()
        with patch.object(servicio, '_bloquear_fuente', side_effect=sincronizar):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futuros = [pool.submit(escritor, entrada) for entrada in entradas]
                resultados = [f.result(timeout=40) for f in futuros]
        self.assertEqual(len({pid for pid, _ in resultados}), 2)
        for _, resultado in resultados:
            self.assertEqual(resultado['errores'], [])
        return [resultado for _, resultado in resultados]

    def test_rss_distintos_misma_canonica_crean_una_publicacion(self):
        entradas = [servicio.EntradaPersistencia(self.rss, self.html),
                    servicio.EntradaPersistencia(replace(self.rss, url='https://misionesonline.net/rss-2'), self.html)]
        resultados = self.ejecutar_concurrentes(entradas)
        self.assertEqual(sum(r['capturados'] for r in resultados), 1)
        self.assertEqual(sum(r['omitidas'] for r in resultados), 1)
        self.assertEqual(Publicacion.objects.count(), 1)
        self.assertEqual(AliasURLPublicacion.objects.count(), 3)
        self.assertEqual(AliasURLPublicacion.objects.values('publicacion_id').distinct().count(), 1)
        self.assertEqual(servicio.persistir_lote(entradas)['omitidas'], 2)

    def test_html_y_pareja_concurrentes_conservan_alias_rss(self):
        resultados = self.ejecutar_concurrentes([
            self.html, servicio.EntradaPersistencia(self.rss, self.html)])
        self.assertEqual(sum(r['capturados'] for r in resultados), 1)
        self.assertEqual(Publicacion.objects.count(), 1)
        self.assertEqual(AliasURLPublicacion.objects.count(), 2)
        self.assertEqual(servicio.persistir_lote([self.rss])['omitidas'], 1)

    def test_rss_identicos_concurrentes_no_duplican_ni_relaciones(self):
        resultados = self.ejecutar_concurrentes([self.rss, self.rss])
        self.assertEqual(sum(r['capturados'] for r in resultados), 1)
        self.assertEqual(Publicacion.objects.count(), 1)
        self.assertEqual(AliasURLPublicacion.objects.count(), 1)
        self.assertTrue(PublicacionEtiqueta.objects.exists())
        self.assertEqual(RegistroDatos.objects.count(), 2)


    def test_bloqueo_postgresql_espera_otra_transaccion_antes_de_resolver_aliases(self):
        import time
        intentando = Event()
        original = servicio._bloquear_fuente
        estado = {}
        def esperar(fuente):
            intentando.set()
            original(fuente)
        def escritor():
            close_old_connections()
            try:
                with connections['default'].cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid()')
                    estado['pid'] = cursor.fetchone()[0]
                    cursor.execute("SET lock_timeout = '10s'")
                return servicio.persistir_lote([self.rss])
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                original(self.fuente)
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid()')
                    titular = cursor.fetchone()[0]
                with patch.object(servicio, '_bloquear_fuente', side_effect=esperar):
                    futuro = pool.submit(escritor)
                    self.assertTrue(intentando.wait(timeout=10))
                    limite = time.monotonic() + 5
                    bloqueado = False
                    while time.monotonic() < limite:
                        with connection.cursor() as cursor:
                            cursor.execute('SELECT pg_blocking_pids(%s)', [estado['pid']])
                            bloqueado = titular in cursor.fetchone()[0]
                        if bloqueado:
                            break
                        Event().wait(0.02)
                    self.assertTrue(bloqueado, 'El segundo backend debe esperar el advisory lock del primero')
                    self.assertFalse(futuro.done())
                    self.assertFalse(Publicacion.objects.exists())
            resultado = futuro.result(timeout=15)
        self.assertEqual(resultado['errores'], [])
        self.assertEqual(resultado['capturados'], 1)


class MigracionAliasAditivaTests(SimpleTestCase):
    def test_migracion_solo_crea_tabla_nueva_sin_backfill_ni_restricciones_historicas(self):
        import importlib
        from django.db import migrations
        modulo = importlib.import_module('core.migrations.0020_aliasurlpublicacion')
        operaciones = modulo.Migration.operations
        self.assertEqual(len(operaciones), 1)
        self.assertIsInstance(operaciones[0], migrations.CreateModel)
        self.assertEqual(operaciones[0].name, 'AliasURLPublicacion')
        restriccion, = operaciones[0].options['constraints']
        self.assertEqual(tuple(restriccion.fields), ('fuente', 'url_normalizada'))
        campos = dict(operaciones[0].fields)
        self.assertEqual(campos['publicacion'].remote_field.model, 'core.publicacion')
