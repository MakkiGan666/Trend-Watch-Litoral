"""Pruebas offline del prototipo de descubrimiento; no requieren Django ni red."""
from pathlib import Path
import unittest
from unittest.mock import patch

from core.services.descubrimiento_historico_sitemap import (
    MAX_ELEMENTOS,
    SitemapInvalido,
    a_json,
    descubrir,
)


FIXTURES = Path(__file__).parent / 'fixtures' / 'historico_sitemap'


def fixture(nombre):
    return (FIXTURES / nombre).read_bytes()


def urlset(*locs):
    entries = ''.join(f'<url><loc>{loc}</loc></url>' for loc in locs)
    return (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f'{entries}</urlset>'
    )


class DescubrimientoSitemapTests(unittest.TestCase):
    def test_urlset_valido_extrae_candidatas_sin_contenido_editorial(self):
        resultado = descubrir(fixture('urlset_valido.xml'))
        self.assertEqual(len(resultado['candidatas']), 2)
        primera = resultado['candidatas'][0]
        self.assertEqual(primera['lastmod'], '2026-10-02T10:30:00Z')
        self.assertEqual(primera['lastmod_estado'], 'VALIDO')
        self.assertIsNone(primera['fecha_publicacion'])
        self.assertFalse(primera['verificada_como_noticia'])
        self.assertNotIn('titulo', primera)
        self.assertNotIn('contenido', primera)
        self.assertEqual(resultado['duplicadas'], 1)

    def test_indice_devuelve_hijos_pendientes_sin_descargarlos(self):
        resultado = descubrir(fixture('indice_valido.xml'))
        self.assertEqual(resultado['tipo_documento'], 'sitemapindex')
        self.assertEqual(len(resultado['sitemaps_pendientes']), 2)
        self.assertTrue(all(not item['descarga_automatica'] for item in resultado['sitemaps_pendientes']))
        self.assertEqual(resultado['sitemaps_pendientes'][0]['lastmod_estado'], 'VALIDO')
        self.assertEqual(resultado['sitemaps_pendientes'][1]['lastmod_estado'], 'AUSENTE')

    def test_hosts_externos_se_rechazan_sin_devolver_la_url(self):
        resultado = descubrir(urlset('https://example.org/noticias/2026/10/01/1-falsa'))
        self.assertEqual(resultado['rechazadas'], [{'indice': 0, 'codigo': 'url_no_admitida'}])

    def test_urls_malformadas_o_con_esquema_no_admitido_se_rechazan(self):
        urls = (
            'http://www.elterritorio.com.ar/noticias/2026/10/01/1-http',
            'https://usuario@www.elterritorio.com.ar/noticias/2026/10/01/2-userinfo',
            'https://www.elterritorio.com.ar\\\\noticias\\2026\\10\\01\\3-backslash',
        )
        for url in urls:
            with self.subTest(url=url):
                resultado = descubrir(urlset(url))
                self.assertEqual(resultado['rechazadas'][0]['codigo'], 'url_no_admitida')

    def test_xml_malformado_se_rechaza(self):
        with self.assertRaisesRegex(SitemapInvalido, 'xml_malformado'):
            descubrir(fixture('malformado.xml'))

    def test_lastmod_ausente_e_invalido_no_se_convierten_en_fecha_publicacion(self):
        resultado = descubrir(fixture('urlset_valido.xml'))
        sin_fecha = resultado['candidatas'][1]
        self.assertEqual(sin_fecha['lastmod_estado'], 'AUSENTE')
        self.assertIsNone(sin_fecha['lastmod'])
        invalida = descubrir(urlset(
            '<bad>https://www.elterritorio.com.ar/noticias/2026/10/01/12345-test</bad>'
        ))
        # Las entidades XML escapadas en datos no se interpretan como etiquetas válidas.
        self.assertEqual(invalida['rechazadas'][0]['codigo'], 'loc_ausente')
        con_lastmod_invalido = (
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url>'
            '<loc>https://www.elterritorio.com.ar/noticias/2026/10/01/12345-test</loc>'
            '<lastmod>ayer</lastmod></url></urlset>'
        )
        item = descubrir(con_lastmod_invalido)['candidatas'][0]
        self.assertEqual(item['lastmod_estado'], 'INVALIDO')
        self.assertIsNone(item['lastmod'])
        self.assertIsNone(item['fecha_publicacion'])

    def test_ruta_que_no_coincide_con_formato_noticia_no_es_candidata(self):
        resultado = descubrir(fixture('urlset_valido.xml'))
        self.assertEqual(resultado['no_candidatas'][0]['codigo'], 'ruta_no_reconocida')
        self.assertEqual(resultado['no_candidatas'][0]['url'], 'https://www.elterritorio.com.ar/seccion/actualidad')

    def test_limite_y_exceso_quedan_contabilizados(self):
        xml = urlset(*[
            f'https://www.elterritorio.com.ar/noticias/2026/10/01/{i}-prueba'
            for i in range(1, 5)
        ])
        resultado = descubrir(xml, limite=2)
        self.assertEqual(len(resultado['candidatas']), 2)
        self.assertEqual(resultado['fuera_limite'], 2)

    def test_rechaza_urls_mas_largas_que_el_campo_destino(self):
        ruta = 'a' * 510
        resultado = descubrir(urlset(
            f'https://www.elterritorio.com.ar/noticias/2026/10/01/123-{ruta}'
        ))
        self.assertEqual(resultado['rechazadas'][0]['codigo'], 'url_demasiado_larga')

    def test_rechaza_dtd_y_entidades_externas(self):
        with self.assertRaisesRegex(SitemapInvalido, 'xml_dtd_no_admitido'):
            descubrir(fixture('entidad_externa.xml'))

    def test_limites_y_tipos_de_entrada(self):
        with self.assertRaises(SitemapInvalido):
            descubrir('')
        with self.assertRaises(SitemapInvalido):
            descubrir(b'x' * (2_000_001))
        for limite in (0, MAX_ELEMENTOS + 1, True, 1.5):
            with self.subTest(limite=limite), self.assertRaises(ValueError):
                descubrir(fixture('urlset_valido.xml'), limite=limite)

    def test_serializacion_json_y_cero_transporte(self):
        with patch('core.services.descarga_segura.descargar', side_effect=AssertionError('No debe haber HTTP')) as descargar:
            resultado = descubrir(fixture('urlset_valido.xml'))
            json_texto = a_json(resultado)
        descargar.assert_not_called()
        self.assertIn('CANDIDATA_NO_VERIFICADA', json_texto)
        item = resultado['candidatas'][0]
        self.assertFalse({'titulo', 'contenido', 'descripcion', 'imagen'} & item.keys())


if __name__ == '__main__':
    unittest.main()
