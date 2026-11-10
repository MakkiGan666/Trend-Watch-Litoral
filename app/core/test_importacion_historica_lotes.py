"""Integración sintética de metadatos históricos con checkpoints H5.8."""
import json
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings

from core.models import (
    ControlSolicitudRSSMetadatos,
    ProcesamientoIAMultifuente,
    Publicacion,
    TrabajoLoteRSSMetadatos,
)
from core.services import lotes_rss_metadatos as lotes
from core.services.contrato_historico_lotes import adaptar_candidatas
from core.services.descarga_segura import descargar
from core.services.descubrimiento_historico_sitemap import descubrir
from core.services.fuentes_rss import FUENTES_HISTORICAS, FUENTES_RSS
from core.services.persistencia_rss_metadatos import persistir_metadatos_rss


FIXTURES = Path(__file__).parent / 'fixtures' / 'historico_sitemap'
FUENTE_ID = 'el_territorio'


def entradas_sinteticas(cantidad):
    urls = [
        f'https://www.elterritorio.com.ar/noticias/2026/10/01/{12345 + i}-nota-sintetica-{i}'
        for i in range(cantidad)
    ]
    xml_items = ''.join(
        f'<url><loc>{url}</loc><lastmod>2026-10-02T10:30:00Z</lastmod></url>'
        for url in urls
    )
    documento = (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f'{xml_items}</urlset>'
    )
    hallazgo = descubrir(documento, limite=cantidad)
    base = json.loads((FIXTURES / 'metadatos_verificados.json').read_text(encoding='utf-8'))
    verificaciones = []
    for indice, url in enumerate(urls):
        registro = dict(base)
        registro['url'] = url
        registro['titulo'] = f'Titular histórico sintético {indice}'
        registro['fecha_publicacion'] = f'2026-10-01T09:{15 + indice:02d}:00-03:00'
        registro['procedencia'] = dict(base['procedencia'])
        verificaciones.append(registro)
    return adaptar_candidatas(hallazgo, verificaciones)['entradas']


class ImportacionHistoricaLotesTests(TestCase):
    def setUp(self):
        self.fuente = FUENTES_HISTORICAS[0]
        self.config = override_settings(
            RSS_METADATOS_FUENTES_HABILITADAS=(FUENTE_ID,),
            RSS_METADATOS_FUENTES_REVISADAS=(FUENTE_ID,),
            RSS_METADATOS_FUENTES_APROBADAS_POR_EQUIPO=(FUENTE_ID,),
            RSS_METADATOS_FUENTES_PERMISO_TITULAR_EXPRESO_VERIFICADO=(),
            RSS_METADATOS_LIMITES_POR_FUENTE={FUENTE_ID: 5},
            RSS_METADATOS_INTERVALOS_SEGUNDOS_POR_FUENTE={FUENTE_ID: 3600},
            RSS_METADATOS_429_SIN_RETRY_AFTER_SEGUNDOS=86400,
        )
        self.config.enable()
        self.addCleanup(self.config.disable)

    def importar(self, entradas, *, tamano=2):
        return lotes.iniciar_lote_historico(
            FUENTE_ID, entradas, tamano_lote=tamano, confirmar_persistencia=True,
        )

    def test_importa_snapshot_y_reanuda_checkpoint_sin_http(self):
        entradas = entradas_sinteticas(3)
        with patch('core.services.lotes_rss_metadatos.leer_rss', side_effect=AssertionError('no RSS GET')) as lector, \
                patch('core.services.descarga_segura.socket.getaddrinfo', side_effect=AssertionError('no HTTP')) as dns:
            parcial = self.importar(entradas, tamano=2)
            trabajo = TrabajoLoteRSSMetadatos.objects.get(pk=parcial['trabajo_id'])
            self.assertEqual(trabajo.origen, TrabajoLoteRSSMetadatos.Origen.HISTORICO)
            self.assertEqual(parcial['estado'], TrabajoLoteRSSMetadatos.Estado.PAUSADO)
            self.assertEqual((parcial['procesadas'], parcial['nuevas']), (2, 2))
            self.assertEqual(sum(i['estado'] == 'PENDIENTE' for i in trabajo.snapshot), 1)
            self.assertEqual(len(trabajo.procedencia['entradas']), 3)
            final = lotes.reanudar_trabajo(trabajo.pk, confirmar_persistencia=True)
            lector.assert_not_called()
            dns.assert_not_called()

        trabajo.refresh_from_db()
        self.assertEqual(final['estado'], TrabajoLoteRSSMetadatos.Estado.COMPLETADO)
        self.assertEqual((final['procesadas'], final['nuevas'], final['errores']), (3, 3, 0))
        self.assertEqual(trabajo.snapshot, [])
        self.assertEqual(len(trabajo.procedencia['entradas']), 3)
        self.assertEqual(Publicacion.objects.count(), 3)
        self.assertTrue(all(not p.contenido and not p.contenido_completo
                            for p in Publicacion.objects.all()))
        self.assertEqual(ControlSolicitudRSSMetadatos.objects.count(), 0)
        self.assertEqual(ProcesamientoIAMultifuente.objects.count(), 0)

    def test_reintento_crea_otro_trabajo_sin_duplicar_publicaciones(self):
        entrada = entradas_sinteticas(1)
        primero = self.importar(entrada, tamano=1)
        segundo = self.importar(entrada, tamano=1)
        self.assertEqual(primero['nuevas'], 1)
        self.assertEqual(segundo['duplicadas'], 1)
        self.assertEqual(Publicacion.objects.count(), 1)
        self.assertEqual(TrabajoLoteRSSMetadatos.objects.count(), 2)
        self.assertEqual(ControlSolicitudRSSMetadatos.objects.count(), 0)

    def test_barreras_operativas_siguen_siendo_obligatorias(self):
        with override_settings(RSS_METADATOS_FUENTES_APROBADAS_POR_EQUIPO=()):
            with self.assertRaisesRegex(ValueError, 'aprobación operativa'):
                lotes.iniciar_lote_historico(
                    FUENTE_ID, entradas_sinteticas(1), tamano_lote=1,
                    confirmar_persistencia=True,
                )
        self.assertEqual(TrabajoLoteRSSMetadatos.objects.count(), 0)

    def test_candidato_crudo_no_se_puede_persistir_como_entrada_verificada(self):
        with self.assertRaisesRegex(ValueError, 'no cumple el contrato verificado'):
            self.importar([{'url': 'https://www.elterritorio.com.ar/noticias/2026/10/01/12345-candidata'}])
        self.assertEqual(TrabajoLoteRSSMetadatos.objects.count(), 0)
        self.assertEqual(Publicacion.objects.count(), 0)

    def test_trabajos_anteriores_conservan_origen_rss_por_defecto(self):
        trabajo = TrabajoLoteRSSMetadatos.objects.create(
            fuente_id='noticias_del_6', tamano_lote=1,
        )
        self.assertEqual(trabajo.origen, TrabajoLoteRSSMetadatos.Origen.RSS)
        self.assertEqual(trabajo.procedencia, {})

    def test_origen_historico_no_se_puede_usar_como_inicio_rss(self):
        with patch('core.services.lotes_rss_metadatos.leer_rss') as lector:
            with self.assertRaisesRegex(ValueError, 'importación histórica'):
                lotes.iniciar_lote(FUENTE_ID, tamano_lote=1, confirmar_persistencia=True)
        lector.assert_not_called()
        self.assertEqual(TrabajoLoteRSSMetadatos.objects.count(), 0)
        self.assertEqual(ControlSolicitudRSSMetadatos.objects.count(), 0)

    def test_fuente_historica_no_se_puede_usar_como_ingesta_rss_h54(self):
        with patch('core.services.persistencia_rss_metadatos.leer_rss') as lector:
            with self.assertRaisesRegex(ValueError, 'sólo admite importación histórica'):
                persistir_metadatos_rss(FUENTE_ID, confirmar_persistencia=True)
        lector.assert_not_called()
        self.assertEqual(ControlSolicitudRSSMetadatos.objects.count(), 0)

    def test_fuente_historica_no_consulta_el_transporte_seguro(self):
        with patch('core.services.descarga_segura.socket.getaddrinfo') as resolver:
            with self.assertRaisesRegex(ValueError, 'sin transporte'):
                descargar('https://www.elterritorio.com.ar/noticias/2026/10/01/12345-nota', fuente=self.fuente)
        resolver.assert_not_called()

    def test_catalogo_rss_y_creacion_abierta_permanecen_separados(self):
        self.assertNotIn(FUENTE_ID, {f.identificador for f in FUENTES_RSS})
        self.assertIsNone(self.fuente.feed)
        self.assertFalse(self.fuente.habilitada)
        parcial = self.importar(entradas_sinteticas(2), tamano=1)
        with self.assertRaisesRegex(ValueError, 'Ya existe un trabajo abierto'):
            self.importar(entradas_sinteticas(1), tamano=1)
        self.assertEqual(TrabajoLoteRSSMetadatos.objects.count(), 1)
        self.assertEqual(parcial['origen'], TrabajoLoteRSSMetadatos.Origen.HISTORICO)
