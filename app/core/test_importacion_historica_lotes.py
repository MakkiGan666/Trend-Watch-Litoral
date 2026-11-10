"""Integración sintética de metadatos históricos con checkpoints H5.8."""
import json
from datetime import datetime, timezone
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
from core.services.contrato_historico_lotes import (
    EntradaHistoricaProcesable,
    MetadatosHistoricosInvalidos,
)
from core.services.descarga_segura import descargar
from core.services.descubrimiento_historico_sitemap import descubrir
from core.services.fuentes_rss import FUENTES_HISTORICAS, FUENTES_RSS
from core.services.persistencia_rss_metadatos import persistir_metadatos_rss
from core.services.lector_rss import NoticiaRSS, ResultadoRSS


FIXTURES = Path(__file__).parent / 'fixtures' / 'historico_sitemap'
FUENTE_ID = 'el_territorio'


def paquete_sintetico(cantidad):
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
    return hallazgo, verificaciones


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
            HISTORICO_IMPORTACION_HABILITADA=True,
        )
        self.config.enable()
        self.addCleanup(self.config.disable)

    def importar(self, descubrimiento, verificaciones, *, tamano=2):
        return lotes.iniciar_lote_historico(
            FUENTE_ID, descubrimiento, verificaciones,
            tamano_lote=tamano, confirmar_persistencia=True,
        )

    def test_importa_snapshot_y_reanuda_checkpoint_sin_http(self):
        paquete = paquete_sintetico(3)
        with patch('core.services.lotes_rss_metadatos.leer_rss', side_effect=AssertionError('no RSS GET')) as lector, \
                patch(
                    'core.services.descarga_segura.socket.getaddrinfo',
                    side_effect=AssertionError('no HTTP'),
                ) as dns:
            parcial = self.importar(*paquete, tamano=2)
            trabajo = TrabajoLoteRSSMetadatos.objects.get(pk=parcial['trabajo_id'])
            self.assertEqual(trabajo.origen, TrabajoLoteRSSMetadatos.Origen.HISTORICO)
            self.assertEqual(parcial['estado'], TrabajoLoteRSSMetadatos.Estado.PAUSADO)
            self.assertEqual((parcial['procesadas'], parcial['nuevas']), (2, 2))
            self.assertEqual(parcial['entradas_feed'], 0)
            self.assertEqual(parcial['entradas_historicas'], 3)
            self.assertEqual(parcial['entradas_pendientes'], 1)
            self.assertEqual(parcial['persistidas'], 2)
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
        paquete = paquete_sintetico(1)
        primero = self.importar(*paquete, tamano=1)
        segundo = self.importar(*paquete, tamano=1)
        self.assertEqual(primero['nuevas'], 1)
        self.assertEqual(segundo['duplicadas'], 1)
        self.assertEqual(Publicacion.objects.count(), 1)
        self.assertEqual(TrabajoLoteRSSMetadatos.objects.count(), 2)
        self.assertEqual(ControlSolicitudRSSMetadatos.objects.count(), 0)

    def test_barreras_operativas_siguen_siendo_obligatorias(self):
        paquete = paquete_sintetico(1)
        with override_settings(RSS_METADATOS_FUENTES_APROBADAS_POR_EQUIPO=()):
            with self.assertRaisesRegex(ValueError, 'aprobación operativa'):
                self.importar(*paquete, tamano=1)
        self.assertEqual(TrabajoLoteRSSMetadatos.objects.count(), 0)

    def test_candidato_crudo_no_se_puede_persistir_como_entrada_verificada(self):
        with self.assertRaises(MetadatosHistoricosInvalidos):
            self.importar(
                {'candidatas': [{'url': 'https://www.elterritorio.com.ar/noticias/2026/10/01/12345-candidata'}]},
                [],
            )
        self.assertEqual(TrabajoLoteRSSMetadatos.objects.count(), 0)
        self.assertEqual(Publicacion.objects.count(), 0)

    def test_objeto_verificada_construido_manualmente_no_es_entrada_del_importador(self):
        noticia = NoticiaRSS(
            'El Territorio', FUENTE_ID, 'Titular fabricado',
            'https://www.elterritorio.com.ar/noticias/2026/10/01/12345-fabricado',
            datetime(2026, 10, 1, tzinfo=timezone.utc), '', '', '',
        )
        fabricada = EntradaHistoricaProcesable(
            noticia, 'VERIFICADA', {'metodo': 'declarado'}, None,
        )
        with self.assertRaises(MetadatosHistoricosInvalidos):
            lotes.iniciar_lote_historico(
                FUENTE_ID, fabricada, [], tamano_lote=1,
                confirmar_persistencia=True,
            )
        self.assertEqual(Publicacion.objects.count(), 0)
        self.assertEqual(TrabajoLoteRSSMetadatos.objects.count(), 0)

    def test_importacion_se_mantiene_cerrada_fuera_de_habilitacion_explicita(self):
        paquete = paquete_sintetico(1)
        with override_settings(HISTORICO_IMPORTACION_HABILITADA=False):
            with self.assertRaisesRegex(ValueError, 'deshabilitada'):
                lotes.iniciar_lote_historico(
                    FUENTE_ID, *paquete, tamano_lote=1,
                    confirmar_persistencia=True,
                )
        self.assertEqual(TrabajoLoteRSSMetadatos.objects.count(), 0)

    def test_procedencia_incompleta_se_rechaza_antes_de_crear_trabajo(self):
        descubrimiento, verificaciones = paquete_sintetico(1)
        verificaciones[0]['procedencia'].pop('metodo')
        with self.assertRaises(MetadatosHistoricosInvalidos):
            self.importar(descubrimiento, verificaciones, tamano=1)
        self.assertEqual(TrabajoLoteRSSMetadatos.objects.count(), 0)

    def test_procedencia_arbitraria_o_excesiva_se_rechaza(self):
        descubrimiento, verificaciones = paquete_sintetico(1)
        verificaciones[0]['procedencia']['campo_no_admitido'] = 'valor'
        with self.assertRaises(MetadatosHistoricosInvalidos):
            self.importar(descubrimiento, verificaciones, tamano=1)
        descubrimiento, verificaciones = paquete_sintetico(1)
        verificaciones[0]['procedencia']['referencia'] = 'x' * 300_000
        with self.assertRaises(MetadatosHistoricosInvalidos):
            self.importar(descubrimiento, verificaciones, tamano=1)
        descubrimiento, verificaciones = paquete_sintetico(1)
        descubrimiento['campo_arbitrario'] = {'anidado': {'demasiado': 'x'}}
        with self.assertRaises(MetadatosHistoricosInvalidos):
            self.importar(descubrimiento, verificaciones, tamano=1)
        descubrimiento, verificaciones = paquete_sintetico(1)
        descubrimiento['campo_arbitrario'] = 'x' * 300_000
        with self.assertRaises(MetadatosHistoricosInvalidos):
            self.importar(descubrimiento, verificaciones, tamano=1)
        self.assertEqual(TrabajoLoteRSSMetadatos.objects.count(), 0)

    def test_url_de_verificacion_debe_corresponder_a_la_candidata(self):
        descubrimiento, verificaciones = paquete_sintetico(1)
        verificaciones[0]['url'] = (
            'https://www.elterritorio.com.ar/noticias/2026/10/01/99999-otra-url'
        )
        with self.assertRaises(MetadatosHistoricosInvalidos):
            self.importar(descubrimiento, verificaciones, tamano=1)
        self.assertEqual(Publicacion.objects.count(), 0)

    def test_fuente_titulo_y_fecha_invalidos_se_rechazan(self):
        descubrimiento, verificaciones = paquete_sintetico(1)
        descubrimiento['fuente_id'] = 'noticias_del_6'
        with self.assertRaises(MetadatosHistoricosInvalidos):
            self.importar(descubrimiento, verificaciones, tamano=1)
        descubrimiento, verificaciones = paquete_sintetico(1)
        verificaciones[0]['titulo'] = ' ' * 4
        with self.assertRaises(MetadatosHistoricosInvalidos):
            self.importar(descubrimiento, verificaciones, tamano=1)
        descubrimiento, verificaciones = paquete_sintetico(1)
        verificaciones[0]['fecha_publicacion'] = 'lastmod'
        verificaciones[0]['procedencia']['fecha_publicacion_origen'] = 'lastmod'
        with self.assertRaises(MetadatosHistoricosInvalidos):
            self.importar(descubrimiento, verificaciones, tamano=1)
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
        parcial = self.importar(*paquete_sintetico(2), tamano=1)
        with self.assertRaisesRegex(ValueError, 'Ya existe un trabajo abierto'):
            self.importar(*paquete_sintetico(1), tamano=1)
        self.assertEqual(TrabajoLoteRSSMetadatos.objects.count(), 1)
        self.assertEqual(parcial['origen'], TrabajoLoteRSSMetadatos.Origen.HISTORICO)

    def test_reporte_rss_conserva_contador_feed_y_no_informa_historicos(self):
        fuente_rss = 'noticias_del_6'
        noticias = tuple(NoticiaRSS(
            'Noticias del 6', fuente_rss, f'Titular RSS sintético {indice}',
            f'https://noticiasdel6.com/noticias/nota-sintetica-{indice}',
            datetime(2026, 10, 1, tzinfo=timezone.utc), '', '', '',
        ) for indice in range(2))
        with override_settings(
            RSS_METADATOS_FUENTES_HABILITADAS=(FUENTE_ID, fuente_rss),
            RSS_METADATOS_FUENTES_REVISADAS=(FUENTE_ID, fuente_rss),
            RSS_METADATOS_FUENTES_APROBADAS_POR_EQUIPO=(FUENTE_ID, fuente_rss),
            RSS_METADATOS_LIMITES_POR_FUENTE={FUENTE_ID: 5, fuente_rss: 5},
            RSS_METADATOS_INTERVALOS_SEGUNDOS_POR_FUENTE={FUENTE_ID: 3600, fuente_rss: 3600},
        ):
            resultado = lotes.iniciar_lote(
                fuente_rss, tamano_lote=1, confirmar_persistencia=True,
                lector=lambda *_args, **_kwargs: ResultadoRSS(noticias, (), 2, 0, (0, 1)),
            )
            trabajo_id = resultado['trabajo_id']
            self.assertEqual(resultado['entradas_feed'], 2)
            self.assertEqual(resultado['entradas_historicas'], 0)
            self.assertEqual(resultado['entradas_pendientes'], 1)
            controles = ControlSolicitudRSSMetadatos.objects.count()
            with patch(
                'core.services.lotes_rss_metadatos.leer_rss',
                side_effect=AssertionError('no debe hacer GET'),
            ) as lector:
                reanudado = lotes.reanudar_trabajo(trabajo_id, confirmar_persistencia=True)
        lector.assert_not_called()
        self.assertEqual(reanudado['estado'], TrabajoLoteRSSMetadatos.Estado.COMPLETADO)
        self.assertEqual(reanudado['entradas_feed'], 2)
        self.assertEqual(reanudado['entradas_historicas'], 0)
        self.assertEqual(reanudado['persistidas'], 2)
        self.assertEqual(ControlSolicitudRSSMetadatos.objects.count(), controles)
