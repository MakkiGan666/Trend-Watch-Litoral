from dataclasses import replace
from datetime import timedelta, timezone as dt_timezone
from threading import Event
from unittest.mock import Mock, patch
from uuid import uuid4

from django.core.management import call_command
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from core.models import (
    CacheRobotsMultifuente,
    ControlServicioIngestaMultifuente,
    ControlSolicitudRSSMetadatos,
    ProgramacionIngestaMultifuente,
    Publicacion,
    RegistroDatos,
    TrabajoIngestaMultifuente,
)
from core.services import (
    descarga_segura, fuentes_rss, lector_rss, orquestador_multifuente,
    planificador_multifuente as planificador,
)
from core.services.persistencia_rss_metadatos import (
    FuenteBloqueada,
    FuenteRSSEnEspera,
    _finalizar_solicitud,
    _reservar_solicitud,
)


class AutomatizacionMultifuenteTests(TestCase):
    def setUp(self):
        self.fuente_base = fuentes_rss.FUENTES_RSS[0]
        self.fuente = replace(self.fuente_base, habilitada=True)
        self.catalogo_patch = patch.object(
            planificador, '_catalogo', return_value={self.fuente.identificador: self.fuente},
        )
        self.catalogo_patch.start()
        self.addCleanup(self.catalogo_patch.stop)

    def programar(self, fuente_id=None, *, intervalo=60, habilitada=True,
                  revisada=True, aprobada=True):
        return ProgramacionIngestaMultifuente.objects.create(
            fuente_id=fuente_id or self.fuente.identificador,
            frecuencia_segundos=intervalo,
            intervalo_segundos=intervalo,
            habilitada=habilitada,
            acceso_revisado=revisada,
            aprobacion_operativa=aprobada,
            proxima_ejecucion=timezone.now(),
        )

    def noticia(self):
        return lector_rss.NoticiaRSS(
            fuente=self.fuente.nombre,
            fuente_id=self.fuente.identificador,
            titulo='Titular sintético de prueba',
            url=f'https://{self.fuente.hosts_permitidos[0]}/noticia-prueba/',
            fecha=timezone.now(), resumen='Resumen sintético breve.',
            contenido_completo='', seccion='',
        )

    def test_fuentes_del_catalogo_y_programaciones_denegadas_por_defecto(self):
        self.assertTrue(all(not fuente.habilitada for fuente in fuentes_rss.FUENTES_RSS))
        plan = planificador.configurar_fuente(self.fuente.identificador, intervalo_segundos=3600)
        self.assertFalse(plan.habilitada)
        self.assertFalse(plan.acceso_revisado)
        self.assertFalse(plan.aprobacion_operativa)
        self.assertEqual(TrabajoIngestaMultifuente.objects.count(), 0)

    def test_configuracion_separa_cadencia_rss_de_minimo_http_y_legacy_preserva_ambos(self):
        plan = planificador.configurar_fuente(
            self.fuente.identificador,
            frecuencia_segundos=86400,
            intervalo_http_segundos=3600,
        )
        self.assertEqual(plan.frecuencia_segundos, 86400)
        self.assertEqual(plan.intervalo_segundos, 3600)
        self.assertFalse(plan.habilitada)
        legacy = planificador.configurar_fuente(self.fuente.identificador, intervalo_segundos=7200)
        self.assertEqual(legacy.frecuencia_segundos, 7200)
        self.assertEqual(legacy.intervalo_segundos, 7200)
        with self.assertRaisesRegex(ValueError, 'No combines'):
            planificador.configurar_fuente(
                self.fuente.identificador, intervalo_segundos=7200, frecuencia_segundos=3600,
            )

    def test_intervalo_http_mayor_que_frecuencia_se_conserva_como_piso_operativo(self):
        ahora = timezone.now()
        plan = self.programar(intervalo=3600)
        ProgramacionIngestaMultifuente.objects.filter(pk=plan.pk).update(
            frecuencia_segundos=900, intervalo_segundos=7200,
        )
        planificador._programar_siguiente(self.fuente.identificador, ahora)
        plan.refresh_from_db()
        self.assertEqual(plan.proxima_ejecucion, ahora + timedelta(seconds=7200))

    def test_espera_h56_conserva_fecha_absoluta_para_reanudar_sin_sondeos_prematuros(self):
        reserva = _reservar_solicitud(self.fuente, 60)
        _finalizar_solicitud(self.fuente, reserva, 60)
        control = ControlSolicitudRSSMetadatos.objects.get(fuente_id=self.fuente.identificador)
        deadline = control.ultimo_intento + timedelta(hours=20)
        # Simula que venció la espera del intervalo base registrada al finalizar
        # robots.txt; ahora la regla Crawl-delay del recurso fija el plazo mayor.
        ControlSolicitudRSSMetadatos.objects.filter(pk=control.pk).update(
            retry_after_hasta=timezone.now() - timedelta(seconds=1),
        )
        with self.assertRaises(FuenteRSSEnEspera) as contexto:
            _reservar_solicitud(self.fuente, 20 * 3600)
        self.assertEqual(contexto.exception.espera_hasta, deadline)

        resultado = {'errores': []}
        orquestador_multifuente._error(
            resultado, 'rss', 'FuenteRSSEnEspera', exc=contexto.exception,
        )
        fecha_reanudacion = planificador._espera_fecha(resultado['errores'][0])
        self.assertEqual(fecha_reanudacion, deadline)

    def test_programacion_usa_cadencia_rss_independiente_del_intervalo_http(self):
        ahora = timezone.now()
        plan = self.programar(intervalo=3600)
        ProgramacionIngestaMultifuente.objects.filter(pk=plan.pk).update(frecuencia_segundos=86400)
        with patch('core.services.planificador_multifuente.settings.RSS_METADATOS_INTERVALOS_SEGUNDOS_POR_FUENTE',
                   {self.fuente.identificador: 7200}):
            planificador._programar_siguiente(self.fuente.identificador, ahora)
        plan.refresh_from_db()
        self.assertEqual(plan.proxima_ejecucion, ahora + timedelta(seconds=86400))

    def test_solicitud_http_usa_minimo_http_y_no_cadencia_rss(self):
        plan = self.programar(intervalo=60)
        ProgramacionIngestaMultifuente.objects.filter(pk=plan.pk).update(
            frecuencia_segundos=86400, intervalo_segundos=7200,
        )
        noticia = self.noticia()
        token = uuid4()
        trabajo = TrabajoIngestaMultifuente.objects.create(
            fuente_id=self.fuente.identificador,
            estado=TrabajoIngestaMultifuente.Estado.PROCESANDO,
            snapshot=[planificador._snapshot_item(0, noticia)],
            snapshot_capturado=timezone.now(),
            token_arrendamiento=token,
            fencing_token=1,
        )
        with patch('core.services.planificador_multifuente.settings.RSS_METADATOS_INTERVALOS_SEGUNDOS_POR_FUENTE',
                   {self.fuente.identificador: 10800}), \
                patch('core.services.planificador_multifuente.orquestador_multifuente.ejecutar_ingesta_multifuente',
                      return_value={'fuentes': [{'fuente': self.fuente.identificador, 'nuevas': 1,
                                                 'duplicadas': 0, 'errores': [], 'noticias': []}]}), \
                patch.object(planificador, 'ControlHTTPConRobots', wraps=planificador.ControlHTTPConRobots) as control:
            planificador._procesar_unidad(trabajo.pk, token, 1, ProgramacionIngestaMultifuente.objects.get(pk=plan.pk))
        self.assertEqual(control.call_args.args[1], 10800)

    def test_cache_robots_se_extiende_solo_hasta_limite_seguro_para_intervalos_largos(self):
        control = planificador.ControlHTTPConRobots(self.fuente, 18 * 3600)
        reglas = b'User-agent: *\nCrawl-delay: 72000\n'
        with patch('core.services.planificador_multifuente.descarga_segura.descargar',
                   return_value=reglas) as descargar:
            parser = control._parser(self.fuente.hosts_permitidos[0])
        descargar.assert_called_once()
        cache = planificador.CacheRobotsMultifuente.objects.get(
            fuente_id=self.fuente.identificador, host=self.fuente.hosts_permitidos[0],
        )
        self.assertEqual(cache.expira - cache.consultado, timedelta(hours=20, minutes=5))
        self.assertEqual(control._intervalo_reglas(parser), 72000)

    def test_cache_robots_respeta_max_age_http_y_bloquea_vigencia_insuficiente(self):
        control = planificador.ControlHTTPConRobots(self.fuente, 3600)
        reglas = b'User-agent: *\nAllow: /\n'

        def descargar_con_max_age(url, **kwargs):
            kwargs['observador_respuesta']({'cache-control': 'public, max-age=7200', 'age': '120'})
            return reglas

        with patch('core.services.planificador_multifuente.descarga_segura.descargar',
                   side_effect=descargar_con_max_age):
            control._parser(self.fuente.hosts_permitidos[0])
        cache = planificador.CacheRobotsMultifuente.objects.get(
            fuente_id=self.fuente.identificador, host=self.fuente.hosts_permitidos[0],
        )
        self.assertEqual(cache.expira - cache.consultado, timedelta(hours=1, minutes=58))

        otro_host = self.fuente.hosts_permitidos[-1]
        control_corto = planificador.ControlHTTPConRobots(self.fuente, 3600)

        def descargar_vigencia_corta(url, **kwargs):
            kwargs['observador_respuesta']({'cache-control': 'max-age=1800'})
            return reglas

        with patch('core.services.planificador_multifuente.descarga_segura.descargar',
                   side_effect=descargar_vigencia_corta):
            with self.assertRaisesRegex(ValueError, 'no cubre el intervalo requerido'):
                control_corto._parser(otro_host)
        self.assertFalse(planificador.CacheRobotsMultifuente.objects.filter(host=otro_host).exists())

    def test_cache_robots_no_reutiliza_respuesta_no_store(self):
        control = planificador.ControlHTTPConRobots(self.fuente, 60)

        def descargar_no_store(url, **kwargs):
            kwargs['observador_respuesta']({'cache-control': 'no-store'})
            return b'User-agent: *\nAllow: /\n'

        with patch('core.services.planificador_multifuente.descarga_segura.descargar',
                   side_effect=descargar_no_store):
            with self.assertRaisesRegex(ValueError, 'Cache-Control impide'):
                control._parser(self.fuente.hosts_permitidos[0])
        self.assertFalse(planificador.CacheRobotsMultifuente.objects.exists())

    def test_intervalo_mayor_que_ventana_robots_falla_cerrado_sin_get(self):
        control = planificador.ControlHTTPConRobots(self.fuente, 24 * 3600)
        with patch('core.services.planificador_multifuente.descarga_segura.descargar') as descargar:
            with self.assertRaisesRegex(ValueError, 'vigencia máxima segura'):
                control._parser(self.fuente.hosts_permitidos[0])
        descargar.assert_not_called()

    def test_regla_robots_superior_a_ventana_no_se_cachea_ni_permite_recurso(self):
        control = planificador.ControlHTTPConRobots(self.fuente, 60)
        reglas = b'User-agent: *\nCrawl-delay: 90000\n'
        with patch('core.services.planificador_multifuente.descarga_segura.descargar',
                   return_value=reglas), patch('core.services.planificador_multifuente._reservar_solicitud') as reservar:
            with self.assertRaisesRegex(ValueError, 'exceden la vigencia máxima segura'):
                control.antes(self.fuente.feed)
        reservar.assert_not_called()
        self.assertFalse(planificador.CacheRobotsMultifuente.objects.exists())

    def test_ciclo_omite_fuente_sin_aprobacion_operativa(self):
        self.programar(aprobada=False)
        with patch('core.services.planificador_multifuente.orquestador_multifuente.ejecutar_ingesta_multifuente') as ejecutar:
            resultado = planificador.ejecutar_ciclo(max_fuentes=1)
        ejecutar.assert_not_called()
        self.assertEqual(resultado['resultados'], [])
        self.assertEqual(TrabajoIngestaMultifuente.objects.count(), 0)

    def test_frecuencia_invalida_y_aprobaciones_incompletas_se_rechazan(self):
        with self.assertRaises(ValueError):
            planificador.configurar_fuente(self.fuente.identificador, intervalo_segundos=59)
        self.programar(habilitada=False, revisada=False, aprobada=False)
        with self.assertRaises(ValueError):
            planificador.habilitar_fuente(
                self.fuente.identificador,
                confirmar_revision_acceso=True,
                confirmar_aprobacion_operativa=False,
            )
        # La operación rechazada no cambia las banderas persistidas.
        plan = ProgramacionIngestaMultifuente.objects.get()
        self.assertFalse(plan.habilitada)
        self.assertFalse(plan.acceso_revisado)
        self.assertFalse(plan.aprobacion_operativa)

    def test_fuente_no_habilitada_en_catalogo_no_puede_activarse_desde_db(self):
        self.catalogo_patch.stop()
        self.catalogo_patch = patch.object(
            planificador, '_catalogo', return_value={self.fuente_base.identificador: self.fuente_base},
        )
        self.catalogo_patch.start()
        self.addCleanup(self.catalogo_patch.stop)
        self.programar()
        with self.assertRaisesRegex(ValueError, 'deshabilitada en el catálogo'):
            planificador.habilitar_fuente(
                self.fuente.identificador, confirmar_revision_acceso=True,
                confirmar_aprobacion_operativa=True,
            )

    def test_fuente_deshabilitada_se_ejecuta_solo_como_snapshot_metadata_only(self):
        fuente_deshabilitada = replace(self.fuente_base, habilitada=False)
        catalogo = patch.object(
            planificador, '_catalogo', return_value={fuente_deshabilitada.identificador: fuente_deshabilitada},
        )
        catalogo.start()
        self.addCleanup(catalogo.stop)
        settings = override_settings(
            RSS_METADATOS_FUENTES_HABILITADAS=(self.fuente.identificador,),
            RSS_METADATOS_FUENTES_REVISADAS=(self.fuente.identificador,),
            RSS_METADATOS_FUENTES_APROBADAS_POR_EQUIPO=(self.fuente.identificador,),
            RSS_METADATOS_FUENTES_PERMISO_TITULAR_EXPRESO_VERIFICADO=(),
            RSS_METADATOS_LIMITES_POR_FUENTE={self.fuente.identificador: 5},
            RSS_METADATOS_INTERVALOS_SEGUNDOS_POR_FUENTE={self.fuente.identificador: 3600},
            RSS_METADATOS_429_SIN_RETRY_AFTER_SEGUNDOS=86400,
        )
        settings.enable()
        self.addCleanup(settings.disable)

        plan = planificador.configurar_fuente(
            self.fuente.identificador, frecuencia_segundos=6 * 3600,
            intervalo_http_segundos=3600, solo_metadatos=True,
        )
        self.assertFalse(plan.habilitada)
        plan = planificador.habilitar_fuente(
            self.fuente.identificador, confirmar_revision_acceso=True,
            confirmar_aprobacion_operativa=True,
        )
        self.assertTrue(plan.habilitada)
        self.assertTrue(plan.solo_metadatos)

        feed = lector_rss.ResultadoRSS(
            noticias=(self.noticia(),), rechazos=(), total_entradas=1, truncadas=0,
            indices_noticias=(0,),
        )

        def capturar_snapshot(identificadores, **kwargs):
            self.assertEqual(identificadores, [self.fuente.identificador])
            self.assertTrue(kwargs['solo_snapshot'])
            self.assertTrue(kwargs['solo_metadatos'])
            self.assertFalse(kwargs['procesar_ia'])
            self.assertIsInstance(kwargs['control_solicitud'], planificador.ControlHTTPConRobots)
            kwargs['guardar_snapshot'](self.fuente.identificador, feed)
            return {'fuentes': [{'fuente': self.fuente.identificador, 'errores': []}]}

        with patch.object(
            planificador.orquestador_multifuente,
            'ejecutar_ingesta_multifuente', side_effect=capturar_snapshot,
        ) as ejecutar:
            primero = planificador.ejecutar_ciclo(max_fuentes=1)
            self.assertEqual(primero['resultados'][0]['estado'], 'SNAPSHOT_GUARDADO')
            trabajo = TrabajoIngestaMultifuente.objects.get()
            self.assertTrue(trabajo.solo_metadatos)
            self.assertNotIn('resumen', trabajo.snapshot[0])
            self.assertNotIn('imagen_principal', trabajo.snapshot[0])
            self.assertNotIn('contenido_completo', trabajo.snapshot[0])

            TrabajoIngestaMultifuente.objects.filter(pk=trabajo.pk).update(
                proxima_accion=timezone.now(),
            )
            segundo = planificador.ejecutar_ciclo(max_fuentes=1)
            trabajo.refresh_from_db()
            self.assertEqual(segundo['resultados'][0]['estado'], 'COMPLETADO')
            self.assertEqual(trabajo.estado, TrabajoIngestaMultifuente.Estado.COMPLETADO)
            self.assertEqual(ejecutar.call_count, 1)

        publicacion = Publicacion.objects.get(pk=trabajo.resultados[0]['publicacion_id'])
        self.assertEqual(publicacion.contenido, '')
        self.assertFalse(publicacion.contenido_completo)

    def test_fuente_sin_modo_metadata_only_sigue_bloqueada_para_activacion(self):
        fuente_deshabilitada = replace(self.fuente_base, habilitada=False)
        catalogo = patch.object(
            planificador, '_catalogo', return_value={fuente_deshabilitada.identificador: fuente_deshabilitada},
        )
        catalogo.start()
        self.addCleanup(catalogo.stop)
        plan = planificador.configurar_fuente(
            self.fuente.identificador, frecuencia_segundos=3600,
            intervalo_http_segundos=3600, solo_metadatos=False,
        )
        with self.assertRaisesRegex(ValueError, 'deshabilitada en el catálogo para extracción completa'):
            planificador.habilitar_fuente(
                self.fuente.identificador, confirmar_revision_acceso=True,
                confirmar_aprobacion_operativa=True,
            )
        self.assertFalse(ProgramacionIngestaMultifuente.objects.get(pk=plan.pk).habilitada)
        with patch.object(
            orquestador_multifuente.descarga_segura, 'descargar',
        ) as descargar:
            with self.assertRaisesRegex(ValueError, 'Fuente deshabilitada'):
                orquestador_multifuente.ejecutar_ingesta_multifuente(
                    [self.fuente.identificador],
                )
        descargar.assert_not_called()

    def test_fuente_metadata_only_sin_gates_h56_no_se_habilita(self):
        fuente_deshabilitada = replace(self.fuente_base, habilitada=False)
        catalogo = patch.object(
            planificador, '_catalogo', return_value={fuente_deshabilitada.identificador: fuente_deshabilitada},
        )
        catalogo.start()
        self.addCleanup(catalogo.stop)
        plan = planificador.configurar_fuente(
            self.fuente.identificador, frecuencia_segundos=6 * 3600,
            intervalo_http_segundos=3600, solo_metadatos=True,
        )
        with self.assertRaisesRegex(ValueError, 'Política RSS metadata-only incompleta'):
            planificador.habilitar_fuente(
                self.fuente.identificador, confirmar_revision_acceso=True,
                confirmar_aprobacion_operativa=True,
            )
        plan.refresh_from_db()
        self.assertFalse(plan.habilitada)
        self.assertFalse(plan.acceso_revisado)
        self.assertFalse(plan.aprobacion_operativa)

    def test_metadata_only_no_admite_articulos_ia_ni_snapshot_inyectado(self):
        for opciones in (
            {'solo_snapshot': False, 'guardar_snapshot': lambda *args: None,
             'control_solicitud': Mock()},
            {'solo_snapshot': True, 'guardar_snapshot': lambda *args: None,
             'control_solicitud': Mock(), 'procesar_ia': True},
            {'solo_snapshot': True, 'guardar_snapshot': lambda *args: None,
             'control_solicitud': Mock(), 'articulo_urls': {self.fuente.identificador: 'https://invalid.test/a'}},
            {'solo_snapshot': True, 'guardar_snapshot': lambda *args: None,
             'control_solicitud': None},
        ):
            with self.subTest(opciones=opciones):
                with self.assertRaisesRegex(ValueError, 'Metadata-only requiere'):
                    orquestador_multifuente.ejecutar_ingesta_multifuente(
                        [self.fuente.identificador], solo_metadatos=True, **opciones,
                    )

    def test_reanudacion_preserva_el_modo_metadata_only_y_no_consulta_articulos(self):
        fuente_deshabilitada = replace(self.fuente_base, habilitada=False)
        catalogo = patch.object(
            planificador, '_catalogo', return_value={fuente_deshabilitada.identificador: fuente_deshabilitada},
        )
        catalogo.start()
        self.addCleanup(catalogo.stop)
        settings = override_settings(
            RSS_METADATOS_FUENTES_HABILITADAS=(self.fuente.identificador,),
            RSS_METADATOS_FUENTES_REVISADAS=(self.fuente.identificador,),
            RSS_METADATOS_FUENTES_APROBADAS_POR_EQUIPO=(self.fuente.identificador,),
            RSS_METADATOS_LIMITES_POR_FUENTE={self.fuente.identificador: 5},
            RSS_METADATOS_INTERVALOS_SEGUNDOS_POR_FUENTE={self.fuente.identificador: 3600},
            RSS_METADATOS_429_SIN_RETRY_AFTER_SEGUNDOS=86400,
        )
        settings.enable()
        self.addCleanup(settings.disable)
        plan = ProgramacionIngestaMultifuente.objects.create(
            fuente_id=self.fuente.identificador, habilitada=True, acceso_revisado=True,
            aprobacion_operativa=True, solo_metadatos=True,
            frecuencia_segundos=3600, intervalo_segundos=3600,
        )
        trabajo = TrabajoIngestaMultifuente.objects.create(
            fuente_id=self.fuente.identificador, solo_metadatos=True,
            estado=TrabajoIngestaMultifuente.Estado.REVISION_MANUAL,
            snapshot=[planificador._snapshot_metadata_item(0, self.noticia())],
            snapshot_capturado=timezone.now(), entradas_snapshot=1, cursor=0,
            registro=RegistroDatos.objects.create(
                fuentes_api=self.fuente.identificador, fecha_ejecucion=timezone.now(),
                estado='EN_PROGRESO', lenguaje='RSS metadata-only',
            ),
            codigo_error='fallo_persistencia_controlado',
        )
        planificador.reanudar_trabajo(trabajo.pk, confirmar_revision=True)
        with patch.object(
            planificador.orquestador_multifuente, 'ejecutar_ingesta_multifuente',
        ) as ejecutar:
            salida = planificador.ejecutar_ciclo(max_fuentes=1)
        ejecutar.assert_not_called()
        trabajo.refresh_from_db()
        self.assertTrue(trabajo.solo_metadatos)
        self.assertEqual(trabajo.estado, TrabajoIngestaMultifuente.Estado.COMPLETADO)
        self.assertEqual(salida['resultados'][0]['estado'], 'COMPLETADO')

    def test_dos_reservas_de_trabajo_no_producen_ejecutores_concurrentes(self):
        plan = self.programar()
        primera = planificador._reservar_trabajo(plan, timezone.now())
        segunda = planificador._reservar_trabajo(plan, timezone.now())
        self.assertIsNotNone(primera)
        self.assertIsNone(segunda)
        trabajo_id, token, fencing = primera
        trabajo = TrabajoIngestaMultifuente.objects.get(pk=trabajo_id)
        with self.assertRaises(planificador.LeasePerdido):
            planificador._verificar_fence(trabajo, '00000000-0000-0000-0000-000000000000', fencing)
        self.assertEqual(trabajo.fencing_token, fencing)
        self.assertEqual(trabajo.token_arrendamiento, token)

    def test_lease_vencido_se_recupera_con_fencing_nuevo(self):
        plan = self.programar()
        anterior = planificador._reservar_trabajo(plan, timezone.now())
        trabajo_id, token_anterior, fence_anterior = anterior
        TrabajoIngestaMultifuente.objects.filter(pk=trabajo_id).update(
            arrendamiento_hasta=timezone.now() - timedelta(seconds=1),
        )
        nuevo = planificador._reservar_trabajo(plan, timezone.now())
        self.assertIsNotNone(nuevo)
        _, token_nuevo, fence_nuevo = nuevo
        trabajo = TrabajoIngestaMultifuente.objects.get(pk=trabajo_id)
        self.assertNotEqual(token_anterior, token_nuevo)
        self.assertGreater(fence_nuevo, fence_anterior)
        with self.assertRaises(planificador.LeasePerdido):
            planificador._verificar_fence(trabajo, token_anterior, fence_anterior)

    @patch('core.services.planificador_multifuente.orquestador_multifuente.ejecutar_ingesta_multifuente')
    def test_snapshot_persistente_se_procesa_en_segundo_ciclo_sin_feed(self, ejecutar):
        self.programar()
        noticia = self.noticia()
        feed = lector_rss.ResultadoRSS(
            noticias=(noticia,), rechazos=(), total_entradas=1, truncadas=0,
            indices_noticias=(0,),
        )
        errores_captura = []
        llamadas_captura = []

        def capturar(ids, **kwargs):
            self.assertEqual(ids, [self.fuente.identificador])
            self.assertTrue(kwargs['solo_snapshot'])
            try:
                kwargs['guardar_snapshot'](self.fuente.identificador, feed)
            except Exception as exc:
                errores_captura.append(exc)
                raise
            return {'fuentes': [{'fuente': self.fuente.identificador, 'errores': []}]}

        def ejecutar_simulado(ids, **kwargs):
            llamadas_captura.append(kwargs)
            if kwargs.get('solo_snapshot', False):
                return capturar(ids, **kwargs)
            return {'fuentes': [{'fuente': self.fuente.identificador, 'nuevas': 1,
                                 'duplicadas': 0, 'errores': [],
                                 'noticias': [{'estado': 'GUARDADA', 'publicacion_id': 901}]}]}

        ejecutar.side_effect = ejecutar_simulado
        primero = planificador.ejecutar_ciclo(max_fuentes=1)
        self.assertTrue(ejecutar.called, repr((primero, llamadas_captura)))
        self.assertFalse(errores_captura, repr(errores_captura))
        trabajo = TrabajoIngestaMultifuente.objects.get()
        self.assertEqual(trabajo.estado, TrabajoIngestaMultifuente.Estado.ESPERA, primero)
        self.assertEqual(trabajo.entradas_snapshot, 1)
        self.assertEqual(trabajo.snapshot[0]['titulo'], noticia.titulo)
        self.assertEqual(primero['resultados'][0]['estado'], 'SNAPSHOT_GUARDADO')

        TrabajoIngestaMultifuente.objects.filter(pk=trabajo.pk).update(proxima_accion=timezone.now())
        segundo = planificador.ejecutar_ciclo(max_fuentes=1)
        llamada = llamadas_captura[1]
        self.assertIn(self.fuente.identificador, llamada['snapshots'])
        self.assertTrue(llamada['omitir_conocidas'])
        self.assertFalse(llamada['procesar_ia'])
        trabajo.refresh_from_db()
        self.assertEqual(segundo['resultados'][0]['estado'], 'PERSISTIDA', segundo)
        self.assertEqual(trabajo.estado, TrabajoIngestaMultifuente.Estado.COMPLETADO)
        self.assertEqual(trabajo.nuevas, 1)
        self.assertEqual(trabajo.resultados[0]['publicacion_id'], 901)
        self.assertEqual(trabajo.snapshot, [])
        self.assertEqual(ejecutar.call_count, 2)

    @patch('core.services.planificador_multifuente.orquestador_multifuente.ejecutar_ingesta_multifuente')
    def test_redireccion_pendiente_se_guarda_y_reanuda_desde_destino(self, ejecutar):
        self.programar()
        destino = f'https://{self.fuente.hosts_permitidos[0]}/feed-canonico/'
        hasta = timezone.now() + timedelta(minutes=5)
        respuesta_redireccion = {'fuentes': [{'fuente': self.fuente.identificador, 'errores': [{
                'codigo': 'DescargaPausada', 'url_reanudacion': destino,
                'espera_hasta': hasta.isoformat(),
            }]}]}
        ejecutar.return_value = respuesta_redireccion
        planificador.ejecutar_ciclo(max_fuentes=1)
        trabajo = TrabajoIngestaMultifuente.objects.get()
        self.assertEqual(trabajo.url_feed_reanudacion, destino)
        self.assertEqual(trabajo.estado, TrabajoIngestaMultifuente.Estado.ESPERA)
        TrabajoIngestaMultifuente.objects.filter(pk=trabajo.pk).update(proxima_accion=timezone.now())

        def reanudar(ids, **kwargs):
            self.assertEqual(kwargs['feed_urls'], {self.fuente.identificador: destino})
            kwargs['guardar_snapshot'](self.fuente.identificador, lector_rss.ResultadoRSS(
                noticias=(self.noticia(),), rechazos=(), total_entradas=1,
                truncadas=0, indices_noticias=(0,),
            ))
            return {'fuentes': [{'fuente': self.fuente.identificador, 'errores': []}]}

        ejecutar.side_effect = reanudar
        # Libera un nuevo ciclo tras la espera sin realizar una llamada HTTP de prueba.
        planificador.ejecutar_ciclo(max_fuentes=1)
        trabajo.refresh_from_db()
        self.assertEqual(trabajo.url_feed_reanudacion, '')
        self.assertEqual(trabajo.entradas_snapshot, 1)

    @patch('core.services.planificador_multifuente.orquestador_multifuente.ejecutar_ingesta_multifuente')
    def test_redireccion_de_articulo_se_guarda_en_el_checkpoint_pendiente(self, ejecutar):
        self.programar()
        noticia = self.noticia()
        item = planificador._snapshot_item(4, noticia)
        TrabajoIngestaMultifuente.objects.create(
            fuente_id=self.fuente.identificador,
            estado=TrabajoIngestaMultifuente.Estado.ESPERA,
            snapshot=[item], snapshot_capturado=timezone.now(),
            entradas_feed=5, entradas_snapshot=1, proxima_accion=timezone.now(),
        )
        destino = f'https://{self.fuente.hosts_permitidos[0]}/noticias/canonica/'
        hasta = timezone.now() + timedelta(minutes=2)
        ejecutar.return_value = {'fuentes': [{
            'fuente': self.fuente.identificador, 'nuevas': 0, 'duplicadas': 0,
            'errores': [{'codigo': 'DescargaPausada', 'url_reanudacion': destino,
                         'espera_hasta': hasta.isoformat()}],
        }]}
        planificador.ejecutar_ciclo(max_fuentes=1)
        trabajo = TrabajoIngestaMultifuente.objects.get()
        self.assertEqual(trabajo.estado, TrabajoIngestaMultifuente.Estado.ESPERA)
        self.assertEqual(trabajo.snapshot[0]['estado'], 'PENDIENTE')
        self.assertEqual(trabajo.snapshot[0]['url_reanudacion'], destino)
        self.assertEqual(trabajo.procesadas, 0)

    def test_intervalo_robots_se_aplica_antes_de_reservar_get(self):
        parser = Mock()
        parser.can_fetch.return_value = True
        parser.crawl_delay.return_value = 180
        parser.request_rate.return_value = None
        control = planificador.ControlHTTPConRobots(self.fuente, 60)
        CacheRobotsMultifuente.objects.create(
            fuente_id=self.fuente.identificador, host=self.fuente.hosts_permitidos[0],
            reglas='User-agent: *\nAllow: /\n', consultado=timezone.now(),
            expira=timezone.now() + timedelta(hours=1),
        )
        with patch.object(control, '_parser', return_value=parser), \
                patch('core.services.planificador_multifuente._reservar_solicitud', return_value=44) as reservar:
            reserva = control.antes(self.fuente.feed)
        self.assertEqual(reserva['intervalo'], 180)
        reservar.assert_called_once_with(self.fuente, 180)

    def test_robots_denegado_no_reserva_ni_descarga_feed(self):
        parser = Mock()
        parser.can_fetch.return_value = False
        control = planificador.ControlHTTPConRobots(self.fuente, 60)
        with patch.object(control, '_parser', return_value=parser), \
                patch('core.services.planificador_multifuente._reservar_solicitud') as reservar:
            with self.assertRaises(planificador.ReglasRobotsDeniegan):
                control.antes(self.fuente.feed)
        reservar.assert_not_called()

    def test_h56_429_y_revision_manual_son_durables(self):
        reserva = _reservar_solicitud(self.fuente, 60)
        _finalizar_solicitud(self.fuente, reserva, 60, retry_after_segundos=600)
        control = ControlSolicitudRSSMetadatos.objects.get(fuente_id=self.fuente.identificador)
        self.assertEqual(control.estado, ControlSolicitudRSSMetadatos.Estado.ESPERA)
        self.assertGreaterEqual(control.retry_after_hasta, timezone.now() + timedelta(seconds=590))
        with self.assertRaises(FuenteRSSEnEspera):
            _reservar_solicitud(self.fuente, 60)

        # El estado de otro medio usa otra fila y mantiene aislamiento.
        otra = fuentes_rss.FUENTES_RSS[1]
        reserva_otra = _reservar_solicitud(otra, 60)
        _finalizar_solicitud(otra, reserva_otra, 60, revision_manual=True)
        self.assertEqual(
            ControlSolicitudRSSMetadatos.objects.get(fuente_id=otra.identificador).estado,
            ControlSolicitudRSSMetadatos.Estado.REVISION_MANUAL,
        )
        self.assertEqual(control.estado, ControlSolicitudRSSMetadatos.Estado.ESPERA)

    def test_403_pasa_a_revision_manual_y_no_se_libera_automaticamente(self):
        reserva = _reservar_solicitud(self.fuente, 60)
        _finalizar_solicitud(self.fuente, reserva, 60, revision_manual=True)
        with self.assertRaises(FuenteBloqueada):
            _reservar_solicitud(self.fuente, 60)

    def test_control_http_persiste_403_y_error_de_red_sin_reintento(self):
        control = planificador.ControlHTTPConRobots(self.fuente, 60)
        reserva = _reservar_solicitud(self.fuente, 60)
        control.respuesta({'control_id': reserva, 'intervalo': 60, 'robots': False},
                          self.fuente.feed, 403, None)
        estado = ControlSolicitudRSSMetadatos.objects.get(fuente_id=self.fuente.identificador)
        self.assertEqual(estado.estado, ControlSolicitudRSSMetadatos.Estado.REVISION_MANUAL)
        with self.assertRaises(FuenteBloqueada):
            _reservar_solicitud(self.fuente, 60)

        otra = fuentes_rss.FUENTES_RSS[1]
        control_otra = planificador.ControlHTTPConRobots(otra, 60)
        reserva_otra = _reservar_solicitud(otra, 60)
        control_otra.error(
            {'control_id': reserva_otra, 'intervalo': 60, 'robots': False},
            otra.feed, TimeoutError('error sintético'),
        )
        estado_otra = ControlSolicitudRSSMetadatos.objects.get(fuente_id=otra.identificador)
        self.assertEqual(estado_otra.estado, ControlSolicitudRSSMetadatos.Estado.ESPERA)
        with self.assertRaises(FuenteRSSEnEspera):
            _reservar_solicitud(otra, 60)

    def test_http_excesivo_no_se_acorta(self):
        control = planificador.ControlHTTPConRobots(self.fuente, 60)
        with patch('core.services.planificador_multifuente._finalizar_solicitud', return_value=(
            ControlSolicitudRSSMetadatos.Estado.REVISION_MANUAL, None,
        )) as finalizar:
            respuesta = control.respuesta(
                {'control_id': 1, 'intervalo': 60, 'robots': False}, self.fuente.feed,
                429, str(366 * 24 * 60 * 60),
            )
        self.assertTrue(respuesta['revision_manual'])
        self.assertIsNone(respuesta['espera_hasta'])
        self.assertTrue(finalizar.call_args.kwargs['revision_manual'])
        self.assertIsNone(finalizar.call_args.kwargs['retry_after_segundos'])

    def test_worker_rechaza_instancia_activa_y_detiene_controladamente(self):
        ControlServicioIngestaMultifuente.objects.create(
            pk=1, activo=True, worker_hasta=timezone.now() + timedelta(minutes=1),
        )
        with self.assertRaisesRegex(ValueError, 'worker activo'):
            planificador.iniciar_worker(stop_event=Event())
        ControlServicioIngestaMultifuente.objects.filter(pk=1).update(activo=False)
        detenido = Event()
        detenido.set()
        with patch('core.services.planificador_multifuente.ejecutar_ciclo') as ciclo:
            resultado = planificador.iniciar_worker(stop_event=detenido)
        ciclo.assert_not_called()
        self.assertEqual(resultado['ciclos_completados'], 0)
        self.assertFalse(planificador.estado_servicio()['activo'])

    def test_transport_interruptible_redirects_after_one_get_without_sleep(self):
        class Respuesta:
            status = 302

            def getheader(self, nombre):
                return f'/feed-canonico/' if nombre.lower() == 'location' else None

        class Conexion:
            sock = object()

            def request(self, *args, **kwargs):
                self.requested = True

            def getresponse(self):
                return Respuesta()

            def close(self):
                pass

        destino = timezone.now() + timedelta(minutes=1)
        control = Mock()
        control.antes.return_value = {'control_id': 10}
        control.respuesta.return_value = {'revision_manual': False, 'espera_hasta': destino}
        with patch('core.services.descarga_segura.socket.getaddrinfo', return_value=[
            (2, 1, 6, '', ('93.184.216.34', 443)),
        ]), patch('core.services.descarga_segura._Conexion', return_value=Conexion()) as conexion:
            with self.assertRaises(descarga_segura.DescargaPausada) as contexto:
                descarga_segura.descargar(
                    self.fuente_base.feed, fuente=self.fuente_base, control_solicitud=control,
                )
        self.assertEqual(contexto.exception.url_reanudacion,
                         f'https://{self.fuente.hosts_permitidos[0]}/feed-canonico/')
        control.antes.assert_called_once_with(self.fuente_base.feed)
        self.assertEqual(conexion.return_value.requested, True)

    def test_error_de_una_fuente_no_impide_continuar_otra(self):
        segunda_base = fuentes_rss.FUENTES_RSS[1]
        segunda = replace(segunda_base, habilitada=True)
        self.catalogo_patch.stop()
        self.catalogo_patch = patch.object(
            planificador, '_catalogo', return_value={
                self.fuente.identificador: self.fuente,
                segunda.identificador: segunda,
            },
        )
        self.catalogo_patch.start()
        self.addCleanup(self.catalogo_patch.stop)
        self.programar()
        self.programar(segunda.identificador)
        with patch('core.services.planificador_multifuente._procesar_unidad',
                   side_effect=[RuntimeError('error sintético'), {'estado': 'ESPERA'}]):
            resultado = planificador.ejecutar_ciclo(max_fuentes=2)
        self.assertEqual(len(resultado['resultados']), 2)
        self.assertEqual(resultado['resultados'][0]['estado'], 'REVISION_MANUAL')
        self.assertEqual(resultado['resultados'][1]['estado'], 'ESPERA')

    def test_estado_no_inicia_ciclo_ni_realiza_http(self):
        with patch('core.services.planificador_multifuente.ejecutar_ciclo') as ciclo:
            call_command('automatizar_ingesta_multifuente', '--estado')
        ciclo.assert_not_called()

    def test_modo_metadata_configurable_y_deshabilitado_por_defecto(self):
        plan = planificador.configurar_fuente(
            self.fuente.identificador, frecuencia_segundos=21600,
            intervalo_http_segundos=3600, solo_metadatos=True,
        )
        self.assertTrue(plan.solo_metadatos)
        self.assertFalse(plan.habilitada)
        self.assertFalse(plan.acceso_revisado)
        self.assertFalse(plan.aprobacion_operativa)
        self.assertFalse(all(f.habilitada for f in fuentes_rss.FUENTES_RSS))
        self.assertEqual(plan.frecuencia_segundos, 21600)

    def test_comando_configura_modo_y_cadencia_sin_habilitar(self):
        call_command(
            'automatizar_ingesta_multifuente', '--configurar',
            '--fuente', self.fuente.identificador,
            '--frecuencia-segundos', '21600', '--intervalo-http-segundos', '3600',
            '--modo', 'metadatos',
        )
        plan = ProgramacionIngestaMultifuente.objects.get(fuente_id=self.fuente.identificador)
        self.assertEqual(plan.frecuencia_segundos, 21600)
        self.assertEqual(plan.intervalo_segundos, 3600)
        self.assertTrue(plan.solo_metadatos)
        self.assertFalse(plan.habilitada)
        self.assertFalse(plan.acceso_revisado)
        self.assertFalse(plan.aprobacion_operativa)

    def test_trabajo_congela_modo_configurado_al_reservarse(self):
        plan = self.programar()
        planificador.ProgramacionIngestaMultifuente.objects.filter(pk=plan.pk).update(solo_metadatos=True)
        info = planificador._reservar_trabajo(plan, timezone.now())
        trabajo = TrabajoIngestaMultifuente.objects.get(pk=info[0])
        self.assertTrue(trabajo.solo_metadatos)
        planificador.ProgramacionIngestaMultifuente.objects.filter(pk=plan.pk).update(solo_metadatos=False)
        self.assertTrue(TrabajoIngestaMultifuente.objects.get(pk=trabajo.pk).solo_metadatos)

    def test_no_cambia_modo_de_trabajo_abierto(self):
        plan = self.programar()
        TrabajoIngestaMultifuente.objects.create(
            fuente_id=self.fuente.identificador,
            estado=TrabajoIngestaMultifuente.Estado.ESPERA,
        )
        with self.assertRaisesRegex(ValueError, 'trabajo abierto'):
            planificador.configurar_fuente(self.fuente.identificador, solo_metadatos=True)
        plan.refresh_from_db()
        self.assertFalse(plan.solo_metadatos)

    def test_snapshot_metadata_no_conserva_resumen_imagen_ni_contenido(self):
        plan = self.programar()
        ProgramacionIngestaMultifuente.objects.filter(pk=plan.pk).update(solo_metadatos=True)
        info = planificador._reservar_trabajo(plan, timezone.now())
        noticia = lector_rss.NoticiaRSS(
            fuente=self.fuente.nombre, fuente_id=self.fuente.identificador,
            titulo='Ficha sintética', url=f'https://{self.fuente.hosts_permitidos[0]}/a/',
            fecha=timezone.now(), resumen='No guardar este resumen',
            contenido_completo='No guardar este cuerpo', seccion='No guardar',
            imagen_principal='https://cdn.invalid/imagen.jpg',
        )
        feed = lector_rss.ResultadoRSS((noticia,), (), 1, 0, (0,))
        planificador._guardar_snapshot(info[0], *info[1:], self.fuente.identificador, feed)
        trabajo = TrabajoIngestaMultifuente.objects.get(pk=info[0])
        self.assertEqual(set(trabajo.snapshot[0]), {
            'indice', 'fuente', 'fuente_id', 'titulo', 'url', 'fecha', 'estado',
        })
        self.assertEqual(trabajo.registro.fuentes_api, self.fuente.identificador)
        self.assertEqual(trabajo.registro.estado, 'EN_PROGRESO')

    def test_captura_metadata_usa_solo_snapshot_sin_ia(self):
        plan = self.programar()
        ProgramacionIngestaMultifuente.objects.filter(pk=plan.pk).update(solo_metadatos=True)
        noticia = lector_rss.NoticiaRSS(
            fuente=self.fuente.nombre, fuente_id=self.fuente.identificador,
            titulo='Noticia metadata sintética',
            url=f'https://{self.fuente.hosts_permitidos[0]}/metadata/',
            fecha=timezone.now(), resumen='no conservar', contenido_completo='',
            seccion='', imagen_principal='https://cdn.invalid/not-used.jpg',
        )
        feed = lector_rss.ResultadoRSS((noticia,), (), 1, 0, (0,))

        def capturar(identificadores, **kwargs):
            self.assertEqual(identificadores, [self.fuente.identificador])
            self.assertTrue(kwargs['solo_snapshot'])
            self.assertTrue(kwargs['solo_metadatos'])
            self.assertFalse(kwargs['procesar_ia'])
            kwargs['guardar_snapshot'](self.fuente.identificador, feed)
            return {'fuentes': [{'fuente': self.fuente.identificador, 'errores': []}]}

        with override_settings(
            RSS_METADATOS_FUENTES_HABILITADAS=(self.fuente.identificador,),
            RSS_METADATOS_FUENTES_REVISADAS=(self.fuente.identificador,),
            RSS_METADATOS_FUENTES_APROBADAS_POR_EQUIPO=(self.fuente.identificador,),
            RSS_METADATOS_LIMITES_POR_FUENTE={self.fuente.identificador: 5},
            RSS_METADATOS_INTERVALOS_SEGUNDOS_POR_FUENTE={self.fuente.identificador: 3600},
            RSS_METADATOS_429_SIN_RETRY_AFTER_SEGUNDOS=86400,
        ), patch.object(
            planificador.orquestador_multifuente, 'ejecutar_ingesta_multifuente',
            side_effect=capturar,
        ) as ejecutar, patch('core.services.extractor_articulos.extraer_articulo') as extractor:
            resultado = planificador.ejecutar_ciclo(max_fuentes=1)
        self.assertEqual(resultado['resultados'][0]['estado'], 'SNAPSHOT_GUARDADO')
        self.assertEqual(ejecutar.call_count, 1)
        extractor.assert_not_called()
        trabajo = TrabajoIngestaMultifuente.objects.get()
        self.assertTrue(trabajo.solo_metadatos)
        self.assertNotIn('resumen', trabajo.snapshot[0])
        self.assertNotIn('imagen_principal', trabajo.snapshot[0])

    def _trabajo_metadata_con_snapshot(self, cantidad=7):
        plan = self.programar()
        ProgramacionIngestaMultifuente.objects.filter(pk=plan.pk).update(solo_metadatos=True)
        autorizacion = override_settings(
            RSS_METADATOS_FUENTES_HABILITADAS=(self.fuente.identificador,),
            RSS_METADATOS_FUENTES_REVISADAS=(self.fuente.identificador,),
            RSS_METADATOS_FUENTES_APROBADAS_POR_EQUIPO=(self.fuente.identificador,),
            RSS_METADATOS_LIMITES_POR_FUENTE={self.fuente.identificador: 5},
            RSS_METADATOS_INTERVALOS_SEGUNDOS_POR_FUENTE={self.fuente.identificador: 60},
            RSS_METADATOS_429_SIN_RETRY_AFTER_SEGUNDOS=86400,
        )
        autorizacion.enable()
        self.addCleanup(autorizacion.disable)
        registro = RegistroDatos.objects.create(
            fuentes_api=self.fuente.identificador, fecha_ejecucion=timezone.now(),
            estado='EN_PROGRESO', lenguaje='RSS metadata-only',
        )
        entradas = []
        for indice in range(cantidad):
            # Índices 0 y 1 comparten identidad para comprobar deduplicación.
            url = f'https://{self.fuente.hosts_permitidos[0]}/nota-{0 if indice == 1 else indice}/'
            entradas.append({
                'indice': indice, 'fuente': self.fuente.nombre,
                'fuente_id': self.fuente.identificador, 'titulo': f'Titular {indice}',
                'url': url, 'fecha': timezone.now().isoformat(), 'estado': 'PENDIENTE',
            })
        return TrabajoIngestaMultifuente.objects.create(
            fuente_id=self.fuente.identificador, solo_metadatos=True, registro=registro,
            estado=TrabajoIngestaMultifuente.Estado.PROCESANDO,
            snapshot=entradas, snapshot_capturado=timezone.now(),
            entradas_feed=cantidad, entradas_snapshot=cantidad,
            token_arrendamiento=uuid4(), fencing_token=1,
        )

    def test_metadata_procesa_maximo_cinco_reanuda_sin_feed_y_deduplica(self):
        trabajo = self._trabajo_metadata_con_snapshot()
        from core.services.persistencia_rss_metadatos import _validar_item
        self.assertEqual(_validar_item(
            planificador._noticia_desde_snapshot_metadata(trabajo.snapshot[0]), self.fuente_base,
        )[0], 'Titular 0')
        token = trabajo.token_arrendamiento
        with patch.object(planificador.descarga_segura, 'descargar') as descargar, \
                patch.object(planificador.orquestador_multifuente, 'ejecutar_ingesta_multifuente') as orquestador:
            primero = planificador._procesar_unidad(
                trabajo.pk, token, trabajo.fencing_token,
                ProgramacionIngestaMultifuente(fuente_id=self.fuente.identificador, solo_metadatos=True),
            )
        descargar.assert_not_called()
        orquestador.assert_not_called()
        self.assertEqual(primero['procesadas'], 5)
        self.assertEqual(primero['duplicadas'], 1, primero)
        trabajo.refresh_from_db()
        self.assertEqual(trabajo.estado, TrabajoIngestaMultifuente.Estado.ESPERA)
        self.assertEqual(trabajo.procesadas, 5)
        self.assertEqual(Publicacion.objects.filter(fuente=self.fuente.nombre).count(), 4)
        trabajo.token_arrendamiento = uuid4()
        trabajo.fencing_token += 1
        trabajo.estado = TrabajoIngestaMultifuente.Estado.PROCESANDO
        trabajo.save(update_fields=['token_arrendamiento', 'fencing_token', 'estado'])
        segundo = planificador._procesar_unidad(
            trabajo.pk, trabajo.token_arrendamiento, trabajo.fencing_token,
            ProgramacionIngestaMultifuente(fuente_id=self.fuente.identificador, solo_metadatos=True),
        )
        trabajo.refresh_from_db()
        self.assertEqual(segundo['procesadas'], 2)
        self.assertEqual(trabajo.estado, TrabajoIngestaMultifuente.Estado.COMPLETADO)
        self.assertEqual(Publicacion.objects.filter(fuente=self.fuente.nombre).count(), 6)
        self.assertEqual(trabajo.nuevas, 6)
        self.assertEqual(trabajo.duplicadas, 1)
        self.assertEqual(trabajo.snapshot, [])
        self.assertEqual(trabajo.registro.estado, 'COMPLETADO')
        primera = Publicacion.objects.get(url=f'https://{self.fuente.hosts_permitidos[0]}/nota-0/')
        self.assertEqual(primera.contenido, '')
        self.assertFalse(primera.contenido_completo)
        self.assertFalse(primera.procesado_ia)
        from django.urls import reverse
        respuesta = self.client.get(reverse('buscar_publicaciones'), {'q': 'Titular 0'})
        self.assertEqual(respuesta.status_code, 200)
        ids = [item['id_publicacion_api'] for item in respuesta.json()['resultados']]
        self.assertIn(primera.pk, ids)

    def test_metadata_respetar_limite_h54_menor_que_maximo_del_worker(self):
        trabajo = self._trabajo_metadata_con_snapshot(cantidad=4)
        with override_settings(
            RSS_METADATOS_LIMITES_POR_FUENTE={self.fuente.identificador: 2},
        ):
            resultado = planificador._procesar_snapshot_metadata(
                trabajo.pk, trabajo.token_arrendamiento, trabajo.fencing_token, self.fuente,
            )
        trabajo.refresh_from_db()
        self.assertEqual(resultado['procesadas'], 2)
        self.assertEqual(trabajo.procesadas, 2)
        self.assertEqual(trabajo.estado, TrabajoIngestaMultifuente.Estado.ESPERA)
        self.assertEqual(Publicacion.objects.filter(fuente=self.fuente.nombre).count(), 1)

    def test_error_de_persistencia_revierte_publicacion_y_checkpoint_juntos(self):
        trabajo = self._trabajo_metadata_con_snapshot(cantidad=1)
        token = trabajo.token_arrendamiento
        from core.services import persistencia_rss_metadatos as persistencia
        original = persistencia._persistir_item

        def guardar_y_fallar(*args, **kwargs):
            original(*args, **kwargs)
            from django.db import DatabaseError
            raise DatabaseError('fallo simulado antes del commit')

        with patch.object(persistencia, '_persistir_item', side_effect=guardar_y_fallar):
            with self.assertRaisesRegex(Exception, 'fallo simulado'):
                planificador._procesar_unidad(
                    trabajo.pk, token, trabajo.fencing_token,
                    ProgramacionIngestaMultifuente(fuente_id=self.fuente.identificador, solo_metadatos=True),
                )
        trabajo.refresh_from_db()
        self.assertEqual(trabajo.snapshot[0]['estado'], 'PENDIENTE')
        self.assertEqual(trabajo.procesadas, 0)
        self.assertFalse(Publicacion.objects.filter(fuente=self.fuente.nombre).exists())

    def test_fence_obsoleto_no_confirma_metadata(self):
        trabajo = self._trabajo_metadata_con_snapshot(cantidad=1)
        trabajo.fencing_token += 1
        trabajo.save(update_fields=['fencing_token'])
        with self.assertRaises(planificador.LeasePerdido):
            planificador._procesar_snapshot_metadata(
                trabajo.pk, trabajo.token_arrendamiento, trabajo.fencing_token - 1, self.fuente,
            )
        self.assertEqual(Publicacion.objects.count(), 0)

    def test_visit_time_respeta_ventana_utc_y_siguiente_inicio(self):
        control = planificador.ControlHTTPConRobots(self.fuente, 60)
        utc = dt_timezone.utc
        fuera = timezone.datetime(2026, 11, 20, 2, 0, tzinfo=utc)
        siguiente = control._espera_visit_time(
            'User-agent: *\nVisit-time: 0300-1200\n', fuera,
        )
        self.assertEqual(siguiente, timezone.datetime(2026, 11, 20, 3, 0, tzinfo=utc))
        dentro = timezone.datetime(2026, 11, 20, 4, 0, tzinfo=utc)
        self.assertIsNone(control._espera_visit_time('User-agent: *\nVisit-time: 0300-1200\n', dentro))

    def test_visit_time_malformado_falla_cerrado(self):
        with self.assertRaisesRegex(ValueError, 'Visit-time'):
            planificador.ControlHTTPConRobots._ventanas_visit_time(
                'User-agent: *\nVisit-time: cuando-se-puede\n',
            )

    def test_visit_time_fuera_de_ventana_no_reserva_solicitud(self):
        control = planificador.ControlHTTPConRobots(self.fuente, 60)
        parser = Mock()
        parser.can_fetch.return_value = True
        reglas = 'User-agent: *\nVisit-time: 0300-1200\n'
        cache = CacheRobotsMultifuente.objects.create(
            fuente_id=self.fuente.identificador,
            host=self.fuente.hosts_permitidos[0], reglas=reglas,
            consultado=timezone.now() - timedelta(minutes=5),
            expira=timezone.now() + timedelta(hours=1),
        )
        fuera = timezone.datetime(2026, 11, 20, 2, 0, tzinfo=dt_timezone.utc)
        with patch.object(control, '_parser', return_value=parser), \
                patch('core.services.planificador_multifuente.timezone.now', return_value=fuera), \
                patch('core.services.planificador_multifuente._reservar_solicitud') as reservar:
            with self.assertRaises(FuenteRSSEnEspera):
                control.antes(self.fuente.feed)
        reservar.assert_not_called()


class OrquestadorMetadataOnlyTests(TransactionTestCase):
    def test_fuente_deshabilitada_consulta_solo_feed_en_snapshot_metadata_only(self):
        fuente = replace(fuentes_rss.FUENTES_RSS[0], habilitada=False)
        xml = f'''<?xml version="1.0" encoding="utf-8"?>
            <rss version="2.0"><channel>
              <item><title>Titular RSS sintético</title>
                <link>https://{fuente.hosts_permitidos[0]}/nota/metadata/</link>
                <pubDate>Fri, 20 Nov 2026 10:00:00 GMT</pubDate>
                <description>Este resumen no debe persistirse.</description>
              </item>
            </channel></rss>'''.encode('utf-8')
        snapshots = []
        control = planificador.ControlHTTPConRobots(fuente, 3600)
        ProgramacionIngestaMultifuente.objects.create(
            fuente_id=fuente.identificador, habilitada=True, acceso_revisado=True,
            aprobacion_operativa=True, solo_metadatos=True,
        )
        with override_settings(
            RSS_METADATOS_FUENTES_HABILITADAS=(fuente.identificador,),
            RSS_METADATOS_FUENTES_REVISADAS=(fuente.identificador,),
            RSS_METADATOS_FUENTES_APROBADAS_POR_EQUIPO=(fuente.identificador,),
            RSS_METADATOS_LIMITES_POR_FUENTE={fuente.identificador: 5},
            RSS_METADATOS_INTERVALOS_SEGUNDOS_POR_FUENTE={fuente.identificador: 3600},
            RSS_METADATOS_429_SIN_RETRY_AFTER_SEGUNDOS=86400,
        ), patch.object(
            orquestador_multifuente.fuentes_rss, 'obtener_fuentes', return_value=(fuente,),
        ), patch.object(
            orquestador_multifuente.descarga_segura, 'descargar', return_value=xml,
        ) as descargar:
            salida = orquestador_multifuente.ejecutar_ingesta_multifuente(
                [fuente.identificador], limite_por_fuente=5, limite_total=5,
                solo_snapshot=True,
                guardar_snapshot=lambda fuente_id, feed: snapshots.append((fuente_id, feed)),
                control_solicitud=control, solo_metadatos=True, procesar_ia=False,
            )
        self.assertEqual(descargar.call_count, 1)
        self.assertEqual(descargar.call_args.args[0], fuente.feed)
        self.assertIs(descargar.call_args.kwargs['control_solicitud'], control)
        self.assertEqual(salida['fuentes'][0]['articulos_descargados'], 0)
        self.assertEqual(salida['fuentes'][0]['feeds_descargados'], 1)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0][0], fuente.identificador)
        self.assertEqual(snapshots[0][1].noticias[0].titulo, 'Titular RSS sintético')

    def test_orquestador_rechaza_metadata_only_sin_programacion_aprobada(self):
        fuente = replace(fuentes_rss.FUENTES_RSS[0], habilitada=False)
        control = planificador.ControlHTTPConRobots(fuente, 3600)
        with override_settings(
            RSS_METADATOS_FUENTES_HABILITADAS=(fuente.identificador,),
            RSS_METADATOS_FUENTES_REVISADAS=(fuente.identificador,),
            RSS_METADATOS_FUENTES_APROBADAS_POR_EQUIPO=(fuente.identificador,),
            RSS_METADATOS_LIMITES_POR_FUENTE={fuente.identificador: 5},
            RSS_METADATOS_INTERVALOS_SEGUNDOS_POR_FUENTE={fuente.identificador: 3600},
            RSS_METADATOS_429_SIN_RETRY_AFTER_SEGUNDOS=86400,
        ), patch.object(
            orquestador_multifuente.fuentes_rss, 'obtener_fuentes', return_value=(fuente,),
        ), patch.object(
            orquestador_multifuente.descarga_segura, 'descargar',
        ) as descargar:
            with self.assertRaisesRegex(ValueError, 'programación metadata-only aprobada'):
                orquestador_multifuente.ejecutar_ingesta_multifuente(
                    [fuente.identificador], solo_snapshot=True,
                    guardar_snapshot=lambda *args: None,
                    control_solicitud=control, solo_metadatos=True,
                )
        descargar.assert_not_called()
