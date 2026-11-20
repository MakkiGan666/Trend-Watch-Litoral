from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from core.models import (
    CandidatoDuplicadoEditorial, GrupoEditorial, MiembroGrupoEditorial,
    Publicacion, TrabajoDeteccionSombraEditorial,
)
from core.services import deteccion_incremental_multifuente as incremental
from core.services.deteccion_sombra_editorial import registrar_candidatos_sombra
from core.services.fuentes_rss import FUENTES_RSS
from core.services.lector_rss import NoticiaRSS
from core.services.persistencia_multifuente import persistir_lote


GATE = 'core.services.deteccion_incremental_multifuente.settings.DETECCION_EDITORIAL_SOMBRA_MULTIFUENTE_HABILITADA'
CUERPO = (
    'El hospital de San Pedro anunció nuevas jornadas de vacunación y atención médica para las '
    'familias de la localidad. Los médicos atenderán consultas de salud durante toda la semana '
    'y ofrecerán controles gratuitos a los vecinos. La directora informó que los turnos se '
    'organizarán en los centros comunitarios, con atención de enfermería y seguimiento para '
    'personas mayores. El cronograma detallado será difundido por las autoridades sanitarias '
    'durante los próximos días.'
)


class GateDeteccionSombraTests(SimpleTestCase):
    @override_settings(DETECCION_EDITORIAL_SOMBRA_MULTIFUENTE_HABILITADA=False)
    def test_gate_permanece_cerrado_por_defecto_y_no_procesa(self):
        resultado = incremental.procesar_cola_incremental()
        self.assertEqual(resultado, {
            'habilitada': False, 'procesados': 0, 'candidatos': 0, 'revision_manual': 0,
        })


class DeteccionSombraIncrementalTests(TestCase):
    def setUp(self):
        self.fuente = next(f for f in FUENTES_RSS if f.identificador == 'noticias_del_6')
        self.fecha = timezone.now() - timedelta(hours=2)

    def noticia(self, numero, *, titulo='Municipio anunció obras para los barrios',
                fuente=None, fecha=None, cuerpo=CUERPO):
        fuente = fuente or self.fuente
        return NoticiaRSS(
            fuente.nombre, fuente.identificador, titulo,
            f'https://{fuente.hosts_permitidos[0]}/nota/{numero}',
            fecha or self.fecha, 'Resumen breve de la noticia.', cuerpo, 'actualidad',
        )

    def crear_publicacion(self, numero, *, fecha=None, fuente=None, titulo='Municipio anunció obras para los barrios',
                          cuerpo=CUERPO, contenido_completo=True):
        return Publicacion.objects.create(
            hash_origen=f'fase3c-{numero}', fuente=fuente or self.fuente.nombre,
            titulo=titulo, url=f'https://{self.fuente.hosts_permitidos[0]}/existente/{numero}',
            fecha_publicacion=fecha or self.fecha, contenido=cuerpo if contenido_completo else '',
            contenido_completo=contenido_completo,
        )

    def encolar(self, publicacion):
        return TrabajoDeteccionSombraEditorial.objects.create(publicacion=publicacion)

    @override_settings(DETECCION_EDITORIAL_SOMBRA_MULTIFUENTE_HABILITADA=True)
    def test_persistencia_crea_outbox_atomico_solo_para_publicacion_nueva(self):
        entrada = self.noticia(1)
        primera = persistir_lote([entrada])
        self.assertEqual(primera['capturados'], 1, primera)
        publicacion = Publicacion.objects.get(url=entrada.url)
        self.assertEqual(TrabajoDeteccionSombraEditorial.objects.get().publicacion_id, publicacion.pk)

        segunda = persistir_lote([entrada])
        self.assertEqual(segunda['omitidas'], 1, segunda)
        self.assertEqual(TrabajoDeteccionSombraEditorial.objects.count(), 1)
        self.assertEqual(CandidatoDuplicadoEditorial.objects.count(), 0)

    @override_settings(DETECCION_EDITORIAL_SOMBRA_MULTIFUENTE_HABILITADA=True)
    def test_fallo_al_crear_outbox_revierte_publicacion_en_la_misma_transaccion(self):
        with patch.object(TrabajoDeteccionSombraEditorial.objects, 'create', side_effect=RuntimeError):
            resultado = persistir_lote([self.noticia(2)])
        self.assertEqual(resultado['capturados'], 0)
        self.assertEqual(Publicacion.objects.count(), 0)
        self.assertEqual(TrabajoDeteccionSombraEditorial.objects.count(), 0)

    @override_settings(DETECCION_EDITORIAL_SOMBRA_MULTIFUENTE_HABILITADA=True)
    def test_procesa_solo_pares_directos_de_misma_fuente_y_no_crea_grupos(self):
        existente = self.crear_publicacion(10)
        otra_fuente = next(f for f in FUENTES_RSS if f.identificador == 'norte_misionero')
        self.crear_publicacion(11, fuente=otra_fuente.nombre)
        nueva = persistir_lote([self.noticia(12)])
        self.assertEqual(nueva['capturados'], 1, nueva)
        nueva_id = nueva['noticias'][0]['publicacion_id']
        self.assertEqual(TrabajoDeteccionSombraEditorial.objects.filter(estado='PENDIENTE').count(), 1)

        resultado = incremental.procesar_cola_incremental()

        self.assertEqual(resultado['procesados'], 1)
        self.assertEqual(resultado['candidatos'], 1)
        candidato = CandidatoDuplicadoEditorial.objects.get()
        self.assertEqual({candidato.publicacion_a_id, candidato.publicacion_b_id}, {existente.pk, nueva_id})
        self.assertEqual(candidato.clasificacion, CandidatoDuplicadoEditorial.Clasificacion.PROBABLE)
        self.assertEqual(TrabajoDeteccionSombraEditorial.objects.get().estado, 'COMPLETADO')
        self.assertEqual(Publicacion.objects.count(), 3)
        self.assertEqual(CandidatoDuplicadoEditorial.objects.count(), 1)
        self.assertFalse(hasattr(candidato, 'grupo_automatico'))

    @override_settings(DETECCION_EDITORIAL_SOMBRA_MULTIFUENTE_HABILITADA=True)
    def test_sin_fecha_o_ventana_excesiva_no_fuerza_comparaciones(self):
        sin_fecha = self.crear_publicacion(20, fecha=None)
        sin_fecha.fecha_publicacion = None
        sin_fecha.save(update_fields=['fecha_publicacion'])
        self.encolar(sin_fecha)
        resultado = incremental.procesar_cola_incremental()
        self.assertEqual(resultado['procesados'], 1)
        self.assertEqual(resultado['candidatos'], 0)

        nueva = self.crear_publicacion(21)
        self.encolar(nueva)
        for numero in range(incremental.MAX_COMPARABLES_POR_PUBLICACION + 1):
            self.crear_publicacion(1000 + numero)
        resultado = incremental.procesar_cola_incremental()
        trabajo = TrabajoDeteccionSombraEditorial.objects.get(publicacion=nueva)
        self.assertEqual(trabajo.estado, TrabajoDeteccionSombraEditorial.Estado.REVISION_MANUAL)
        self.assertEqual(trabajo.codigo_error, 'VENTANA_COMPARACION_EXCEDIDA')
        self.assertEqual(resultado['revision_manual'], 1)

    @override_settings(DETECCION_EDITORIAL_SOMBRA_MULTIFUENTE_HABILITADA=True)
    def test_no_reconcilia_ni_reevalua_la_cola_historica_en_cada_ciclo(self):
        anterior_a = self.crear_publicacion(30, fecha=self.fecha - timedelta(days=90))
        anterior_b = self.crear_publicacion(31, fecha=self.fecha - timedelta(days=90))
        evaluacion = {
            'publicaciones': [{'pk': anterior_a.pk}, {'pk': anterior_b.pk}],
        }
        registrar_candidatos_sombra([evaluacion])
        candidato = CandidatoDuplicadoEditorial.objects.get()
        veces = candidato.veces_detectado

        nueva = self.crear_publicacion(32)
        self.encolar(nueva)
        incremental.procesar_cola_incremental()

        candidato.refresh_from_db()
        self.assertEqual(candidato.veces_detectado, veces)

    @override_settings(DETECCION_EDITORIAL_SOMBRA_MULTIFUENTE_HABILITADA=True)
    def test_no_cambia_agrupaciones_editoriales_vigentes(self):
        a = self.crear_publicacion(35)
        b = self.crear_publicacion(36)
        usuario = get_user_model().objects.create_user(username='fase3c-editor')
        grupo = GrupoEditorial.objects.create(
            representante=a, estado=GrupoEditorial.Estado.ACTIVO, creado_por=usuario,
            aprobado_por=usuario, aprobado=timezone.now(), motivo_aprobacion='Grupo fixture vigente',
        )
        for publicacion, rol in (
            (a, MiembroGrupoEditorial.Rol.REPRESENTANTE),
            (b, MiembroGrupoEditorial.Rol.MIEMBRO),
        ):
            MiembroGrupoEditorial.objects.create(
                grupo=grupo, publicacion=publicacion, rol=rol,
                decision=MiembroGrupoEditorial.Decision.APROBADO,
                evidencia={'fixture': True}, huella_publicacion='a' * 64,
                revisado_por=usuario, revisado=timezone.now(),
                motivo_revision='Aprobado en fixture', vigente=True,
            )
        nueva = self.crear_publicacion(37)
        self.encolar(nueva)

        resultado = incremental.procesar_cola_incremental()

        grupo.refresh_from_db()
        self.assertEqual(resultado['procesados'], 1)
        self.assertEqual(resultado['candidatos'], 0)
        self.assertEqual(grupo.estado, GrupoEditorial.Estado.ACTIVO)
        self.assertEqual(MiembroGrupoEditorial.objects.filter(grupo=grupo, vigente=True).count(), 2)
        self.assertEqual(CandidatoDuplicadoEditorial.objects.count(), 0)
        self.assertEqual(Publicacion.objects.count(), 3)

    @override_settings(DETECCION_EDITORIAL_SOMBRA_MULTIFUENTE_HABILITADA=True)
    def test_fallos_se_reintentan_y_terminan_en_revision_manual(self):
        publicacion = self.crear_publicacion(40)
        self.encolar(publicacion)
        with patch.object(incremental, '_candidatos_para', side_effect=RuntimeError('fallo')):
            for _ in range(incremental.MAX_INTENTOS):
                incremental.procesar_cola_incremental()
        trabajo = TrabajoDeteccionSombraEditorial.objects.get()
        self.assertEqual(trabajo.intentos, incremental.MAX_INTENTOS)
        self.assertEqual(trabajo.estado, TrabajoDeteccionSombraEditorial.Estado.REVISION_MANUAL)
        self.assertEqual(trabajo.codigo_error, 'RuntimeError')

    @override_settings(DETECCION_EDITORIAL_SOMBRA_MULTIFUENTE_HABILITADA=True)
    def test_worker_consume_outbox_aunque_no_haya_fuentes_programadas(self):
        self.crear_publicacion(50)
        nueva = self.crear_publicacion(51)
        self.encolar(nueva)
        with patch.object(incremental, 'procesar_cola_incremental', wraps=incremental.procesar_cola_incremental) as procesar:
            from core.services import planificador_multifuente
            resultado = planificador_multifuente.ejecutar_ciclo(max_fuentes=1)
        self.assertEqual(resultado['fuentes_consideradas'], 0)
        self.assertEqual(resultado['deteccion_editorial']['procesados'], 1)
        procesar.assert_called_once()


@override_settings(DETECCION_EDITORIAL_SOMBRA_MULTIFUENTE_HABILITADA=True)
class DeteccionSombraConcurrenciaTests(TransactionTestCase):
    reset_sequences = True

    @patch(GATE, True)
    def test_dos_consumidores_no_procesan_dos_veces_el_mismo_outbox(self):
        if connection.vendor != 'postgresql':
            self.skipTest('La concurrencia usa FOR UPDATE SKIP LOCKED de PostgreSQL.')
        fuente = next(f for f in FUENTES_RSS if f.identificador == 'noticias_del_6')
        base = timezone.now() - timedelta(hours=1)
        texto = CUERPO
        Publicacion.objects.create(
            hash_origen='fase3c-conc-a', fuente=fuente.nombre, titulo='Municipio anunció obras para los barrios',
            url=f'https://{fuente.hosts_permitidos[0]}/conc/a', fecha_publicacion=base,
            contenido=texto, contenido_completo=True,
        )
        nueva = Publicacion.objects.create(
            hash_origen='fase3c-conc-b', fuente=fuente.nombre, titulo='Municipio anunció obras para los barrios',
            url=f'https://{fuente.hosts_permitidos[0]}/conc/b', fecha_publicacion=base,
            contenido=texto, contenido_completo=True,
        )
        TrabajoDeteccionSombraEditorial.objects.create(publicacion=nueva)
        barrera = Barrier(2)

        def consumir():
            close_old_connections()
            try:
                barrera.wait(timeout=3)
                return incremental.procesar_cola_incremental()
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = list(executor.map(lambda _: consumir(), range(2)))

        self.assertEqual(TrabajoDeteccionSombraEditorial.objects.get().estado, 'COMPLETADO')
        self.assertEqual(CandidatoDuplicadoEditorial.objects.count(), 1)
        self.assertEqual(sum(r['procesados'] for r in resultados), 1)
