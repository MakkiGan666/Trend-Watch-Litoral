"""Pruebas de lotes RSS sin red y con snapshots sintéticos."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone as dt_timezone
from threading import Event
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from core.models import (
    ControlSolicitudRSSMetadatos,
    ProcesamientoIAMultifuente,
    Publicacion,
    TrabajoLoteRSSMetadatos,
)
from core.services import lotes_rss_metadatos as lotes
from core.services.descarga_segura import RespuestaHTTPError
from core.services.fuentes_rss import FUENTES_RSS
from core.services.lector_rss import NoticiaRSS, ResultadoRSS


def noticias(fuente, cantidad, *, invalida=()):
    valores = []
    for indice in range(cantidad):
        host = 'host-ajeno.invalid' if indice in invalida else fuente.hosts_permitidos[0]
        valores.append(NoticiaRSS(
            fuente.nombre, fuente.identificador, f'Titular sintético {indice}',
            f'https://{host}/nota/{indice}',
            datetime(2026, 11, 1, 12, indice, tzinfo=dt_timezone.utc),
            'resumen que no debe persistirse', 'cuerpo que no debe persistirse', 'sección',
        ))
    return ResultadoRSS(tuple(valores), (), cantidad, 0, tuple(range(cantidad)))


class LotesRSSMetadatosTests(TestCase):
    def setUp(self):
        self.fuente = FUENTES_RSS[3]
        self.config = override_settings(
            RSS_METADATOS_FUENTES_HABILITADAS=(self.fuente.identificador,),
            RSS_METADATOS_FUENTES_REVISADAS=(self.fuente.identificador,),
            RSS_METADATOS_FUENTES_APROBADAS_POR_EQUIPO=(self.fuente.identificador,),
            RSS_METADATOS_FUENTES_PERMISO_TITULAR_EXPRESO_VERIFICADO=(),
            RSS_METADATOS_LIMITES_POR_FUENTE={self.fuente.identificador: 5},
            RSS_METADATOS_INTERVALOS_SEGUNDOS_POR_FUENTE={self.fuente.identificador: 3600},
            RSS_METADATOS_429_SIN_RETRY_AFTER_SEGUNDOS=86400,
        )
        self.config.enable()
        self.addCleanup(self.config.disable)

    def _iniciar(self, lectura, *, tamano=2, lector=None):
        lector = lector or (lambda fuente, *, limite_entradas: lectura)
        return lotes.iniciar_lote(
            self.fuente.identificador, tamano_lote=tamano,
            confirmar_persistencia=True, lector=lector,
        )

    def test_lote_procesa_varias_y_deja_checkpoint_sin_perder_resto(self):
        lectura = noticias(self.fuente, 7)
        lector = patch('core.services.lotes_rss_metadatos.leer_rss', return_value=lectura)
        with lector as mock_lector:
            resultado = lotes.iniciar_lote(
                self.fuente.identificador, tamano_lote=2, confirmar_persistencia=True,
            )
        trabajo = TrabajoLoteRSSMetadatos.objects.get(pk=resultado['trabajo_id'])
        self.assertEqual(mock_lector.call_count, 1)
        mock_lector.assert_called_once_with(self.fuente, limite_entradas=30)
        self.assertEqual((resultado['estado'], resultado['nuevas'], resultado['procesadas']),
                         ('PAUSADO', 2, 2))
        self.assertEqual(trabajo.entradas_feed, 7)
        self.assertEqual(trabajo.entradas_snapshot, 7)
        self.assertEqual(sum(item['estado'] == 'PENDIENTE' for item in trabajo.snapshot), 5)
        self.assertTrue(all(set(item) <= {'indice', 'estado', 'titulo', 'url', 'fecha', 'codigo'}
                            for item in trabajo.snapshot))

    def test_reanudar_usa_snapshot_sin_get_y_no_duplica(self):
        resultado = self._iniciar(noticias(self.fuente, 3), tamano=1)
        with patch('core.services.lotes_rss_metadatos.leer_rss', side_effect=AssertionError('GET no permitido')) as lector:
            segundo = lotes.reanudar_trabajo(resultado['trabajo_id'], confirmar_persistencia=True)
            final = lotes.reanudar_trabajo(resultado['trabajo_id'], confirmar_persistencia=True)
        lector.assert_not_called()
        self.assertEqual((segundo['nuevas'], segundo['estado']), (2, 'PAUSADO'))
        self.assertEqual((final['nuevas'], final['estado']), (3, 'COMPLETADO'))
        self.assertEqual(Publicacion.objects.count(), 3)
        self.assertEqual(final['procesadas'], 3)

    def test_duplicados_usan_identidad_y_alias_existentes(self):
        item = noticias(self.fuente, 1).noticias[0]
        resultado = self._iniciar(ResultadoRSS((item, item), (), 2, 0, (0, 1)), tamano=2)
        self.assertEqual((resultado['nuevas'], resultado['duplicadas']), (1, 1))
        self.assertEqual(Publicacion.objects.count(), 1)

    def test_entrada_invalida_se_reporta_sin_descartar_entradas_validas(self):
        lectura = noticias(self.fuente, 3, invalida=(1,))
        resultado = self._iniciar(lectura, tamano=3)
        self.assertEqual((resultado['nuevas'], resultado['rechazadas']), (2, 1))
        self.assertEqual(Publicacion.objects.count(), 2)
        self.assertIn('RECHAZADA', [r['estado'] for r in resultado['resultados']])

    def test_ficha_no_guarda_cuerpo_y_no_crea_trabajo_ia(self):
        resultado = self._iniciar(noticias(self.fuente, 1), tamano=1)
        publicacion = Publicacion.objects.get(pk=resultado['resultados'][0]['publicacion_id'])
        self.assertEqual(publicacion.contenido, '')
        self.assertFalse(publicacion.contenido_completo)
        self.assertFalse(publicacion.procesado_ia)
        self.assertFalse(ProcesamientoIAMultifuente.objects.exists())

    def test_status_no_consulta_feed(self):
        resultado = self._iniciar(noticias(self.fuente, 1), tamano=1)
        with patch('core.services.lotes_rss_metadatos.leer_rss', side_effect=AssertionError('No GET en status')):
            estado = lotes.consultar_trabajo(resultado['trabajo_id'])
        self.assertEqual(estado['estado'], 'COMPLETADO')

    def test_http_429_durable_sin_reintento(self):
        lector = patch(
            'core.services.lotes_rss_metadatos.leer_rss',
            side_effect=RespuestaHTTPError(429, retry_after_segundos=7200),
        )
        with lector as mock_lector:
            primero = lotes.iniciar_lote(
                self.fuente.identificador, tamano_lote=1,
                confirmar_persistencia=True,
            )
            segundo = lotes.iniciar_lote(
                self.fuente.identificador, tamano_lote=1,
                confirmar_persistencia=True,
            )
        self.assertEqual(primero['estado'], 'FALLIDO')
        self.assertEqual(segundo['codigo_error'], 'intervalo_minimo_no_vencido')
        self.assertEqual(mock_lector.call_count, 1)
        control = ControlSolicitudRSSMetadatos.objects.get(fuente_id=self.fuente.identificador)
        self.assertEqual(control.estado, ControlSolicitudRSSMetadatos.Estado.ESPERA)
        self.assertGreaterEqual((control.retry_after_hasta - timezone.now()).total_seconds(), 7100)

    def test_recuperacion_de_token_interrumpido_es_explicita_y_no_hace_get(self):
        resultado = self._iniciar(noticias(self.fuente, 2), tamano=1)
        with self.assertRaises(ValueError):
            lotes.recuperar_trabajo(resultado['trabajo_id'])
        token, _ = lotes._reclamar(resultado['trabajo_id'])
        self.assertIsNotNone(token)
        with patch('core.services.lotes_rss_metadatos.leer_rss', side_effect=AssertionError('No GET')):
            recuperado = lotes.recuperar_trabajo(
                resultado['trabajo_id'], confirmar_ejecutor_detenido=True,
            )
            final = lotes.reanudar_trabajo(resultado['trabajo_id'], confirmar_persistencia=True)
        self.assertEqual(recuperado['estado'], 'PAUSADO')
        self.assertEqual(final['nuevas'], 2)

    def test_falla_si_no_hay_confirmacion_o_barreras(self):
        lector = patch('core.services.lotes_rss_metadatos.leer_rss')
        with lector as mock_lector:
            with self.assertRaises(ValueError):
                lotes.iniciar_lote(self.fuente.identificador, confirmar_persistencia=False)
            mock_lector.assert_not_called()

    def test_control_h56_esta_en_curso_antes_de_llamar_al_lector(self):
        def lector(fuente, *, limite_entradas):
            control = ControlSolicitudRSSMetadatos.objects.get(fuente_id=fuente.identificador)
            self.assertEqual(control.estado, ControlSolicitudRSSMetadatos.Estado.EN_CURSO)
            self.assertEqual(limite_entradas, fuente.limite_noticias)
            return noticias(fuente, 1)

        resultado = self._iniciar(noticias(self.fuente, 1), tamano=1, lector=lector)
        self.assertEqual(resultado['estado'], 'COMPLETADO')

    def test_lector_reporta_entradas_omitidas_por_tope_de_snapshot(self):
        from core.services.lector_rss import analizar_rss

        host = self.fuente.hosts_permitidos[0]
        datos = (f'<rss version="2.0"><channel><title>Feed</title>'
                 + ''.join(
                     f'<item><title>Título {i}</title><link>https://{host}/n/{i}</link></item>'
                     for i in range(3)
                 ) + '</channel></rss>').encode()
        lectura = analizar_rss(datos, self.fuente, limite_entradas=2)
        self.assertEqual((lectura.total_entradas, lectura.truncadas), (3, 1))
        self.assertEqual(lectura.indices_noticias, (0, 1))

    def test_pausa_y_reanudacion_son_explicitas_y_no_consultan_de_nuevo(self):
        resultado = self._iniciar(noticias(self.fuente, 3), tamano=1)
        pausado = lotes.pausar_trabajo(resultado['trabajo_id'])
        self.assertEqual(pausado['estado'], 'PAUSADO')
        with patch('core.services.lotes_rss_metadatos.leer_rss', side_effect=AssertionError('No GET')):
            final = lotes.reanudar_trabajo(resultado['trabajo_id'], confirmar_persistencia=True)
        self.assertEqual(final['estado'], 'PAUSADO')
        self.assertEqual(final['nuevas'], 2)


class LotesRSSConcurrenciaTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.fuente = FUENTES_RSS[3]
        self.config = override_settings(
            RSS_METADATOS_FUENTES_HABILITADAS=(self.fuente.identificador,),
            RSS_METADATOS_FUENTES_REVISADAS=(self.fuente.identificador,),
            RSS_METADATOS_FUENTES_APROBADAS_POR_EQUIPO=(self.fuente.identificador,),
            RSS_METADATOS_LIMITES_POR_FUENTE={self.fuente.identificador: 2},
            RSS_METADATOS_INTERVALOS_SEGUNDOS_POR_FUENTE={self.fuente.identificador: 3600},
            RSS_METADATOS_429_SIN_RETRY_AFTER_SEGUNDOS=86400,
        )
        self.config.enable()
        self.addCleanup(self.config.disable)

    def test_dos_procesadores_no_reclaman_el_mismo_trabajo(self):
        lectura = noticias(self.fuente, 2)
        resultado = lotes.iniciar_lote(
            self.fuente.identificador, tamano_lote=1, confirmar_persistencia=True,
            lector=lambda fuente, *, limite_entradas: lectura,
        )
        entrando, continuar = Event(), Event()
        original = lotes._procesar_item

        def bloqueado(*args, **kwargs):
            entrando.set()
            continuar.wait(timeout=10)
            return original(*args, **kwargs)

        def ejecutar():
            close_old_connections()
            try:
                return lotes.reanudar_trabajo(resultado['trabajo_id'], confirmar_persistencia=True)
            finally:
                close_old_connections()

        with patch('core.services.lotes_rss_metadatos._procesar_item', side_effect=bloqueado):
            with ThreadPoolExecutor(max_workers=2) as pool:
                primero = pool.submit(ejecutar)
                self.assertTrue(entrando.wait(timeout=10))
                with self.assertRaises(ValueError):
                    lotes.reanudar_trabajo(resultado['trabajo_id'], confirmar_persistencia=True)
                continuar.set()
                final = primero.result(timeout=15)
        self.assertEqual(final['estado'], 'COMPLETADO')
        self.assertEqual(Publicacion.objects.count(), 2)

    def test_interrupcion_despues_de_checkpoint_preserva_el_resto(self):
        resultado = lotes.iniciar_lote(
            self.fuente.identificador, tamano_lote=1, confirmar_persistencia=True,
            lector=lambda fuente, *, limite_entradas: noticias(fuente, 3),
        )
        trabajo = TrabajoLoteRSSMetadatos.objects.get(pk=resultado['trabajo_id'])
        TrabajoLoteRSSMetadatos.objects.filter(pk=trabajo.pk).update(tamano_lote=2)
        original = lotes._procesar_item
        llamadas = {'n': 0}

        def interrumpir_despues_del_commit(*args, **kwargs):
            llamadas['n'] += 1
            respuesta = original(*args, **kwargs)
            if llamadas['n'] == 1:
                raise KeyboardInterrupt
            return respuesta

        with patch('core.services.lotes_rss_metadatos._procesar_item', side_effect=interrumpir_despues_del_commit):
            with self.assertRaises(KeyboardInterrupt):
                lotes.reanudar_trabajo(trabajo.pk, confirmar_persistencia=True)
        trabajo.refresh_from_db()
        self.assertEqual(trabajo.estado, TrabajoLoteRSSMetadatos.Estado.PAUSADO)
        self.assertEqual(trabajo.nuevas, 2)
        self.assertEqual(sum(i['estado'] == 'PENDIENTE' for i in trabajo.snapshot), 1)
        final = lotes.reanudar_trabajo(trabajo.pk, confirmar_persistencia=True)
        self.assertEqual((final['estado'], final['nuevas']), ('COMPLETADO', 3))
        self.assertEqual(Publicacion.objects.count(), 3)
