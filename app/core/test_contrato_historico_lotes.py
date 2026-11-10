"""Pruebas offline del contrato histórico; no requieren DB ni red."""
import json
from pathlib import Path
import unittest

from core.services.contrato_historico_lotes import (
    MetadatosHistoricosInvalidos,
    adaptar_candidatas,
)
from core.services.descubrimiento_historico_sitemap import descubrir


FIXTURES = Path(__file__).parent / 'fixtures' / 'historico_sitemap'
URL = 'https://www.elterritorio.com.ar/noticias/2026/10/01/12345-titular-de-prueba'


def candidato():
    return descubrir((FIXTURES / 'urlset_valido.xml').read_bytes(), limite=1)


def verificacion():
    return json.loads((FIXTURES / 'metadatos_verificados.json').read_text(encoding='utf-8'))


class ContratoHistoricoLotesTests(unittest.TestCase):
    def test_solo_verificacion_editorial_explicita_produce_entrada_rss(self):
        resultado = adaptar_candidatas(candidato(), [verificacion()])
        self.assertEqual(len(resultado['entradas']), 1)
        entrada = resultado['entradas'][0]
        self.assertEqual(entrada.estado_validacion, 'VERIFICADA')
        self.assertEqual(entrada.noticia.fuente_id, 'el_territorio')
        self.assertEqual(entrada.noticia.titulo, 'Titular sintético para prueba')
        self.assertEqual(entrada.noticia.url, URL)
        self.assertEqual(entrada.noticia.fecha.isoformat(), '2026-10-01T12:15:00+00:00')
        self.assertEqual(entrada.noticia.resumen, '')
        self.assertEqual(entrada.noticia.contenido_completo, '')
        self.assertEqual(entrada.lastmod_sitemap, '2026-10-02T10:30:00Z')
        self.assertEqual(
            entrada.procedencia['verificacion']['fecha_publicacion_origen'],
            'fecha_publicacion_del_indice',
        )

    def test_candidato_sin_verificacion_no_se_convierte(self):
        resultado = adaptar_candidatas(candidato(), [])
        self.assertEqual(resultado['entradas'], [])
        self.assertEqual(resultado['rechazadas'][0]['codigo'], 'url_no_verificada_como_noticia')

    def test_titulo_ausente_se_rechaza(self):
        registro = verificacion()
        registro['titulo'] = '  '
        resultado = adaptar_candidatas(candidato(), [registro])
        self.assertEqual(resultado['rechazadas'][0]['codigo'], 'titulo_ausente_o_invalido')

    def test_fecha_ausente_invalida_o_sin_zona_se_rechaza(self):
        for fecha in (None, 'ayer', '2026-10-01T09:15:00'):
            with self.subTest(fecha=fecha):
                registro = verificacion()
                registro['fecha_publicacion'] = fecha
                resultado = adaptar_candidatas(candidato(), [registro])
                self.assertEqual(resultado['entradas'], [])

    def test_lastmod_no_se_acepta_como_fecha_editorial(self):
        registro = verificacion()
        registro['fecha_publicacion'] = registro['lastmod'] = '2026-10-02T10:30:00Z'
        registro['procedencia']['fecha_publicacion_origen'] = 'sitemap_lastmod'
        resultado = adaptar_candidatas(candidato(), [registro])
        self.assertEqual(resultado['rechazadas'][0]['codigo'], 'lastmod_no_es_fecha_editorial')

    def test_host_no_permitido_se_rechaza(self):
        datos = candidato()
        datos['candidatas'][0]['url'] = 'https://example.org/noticias/2026/10/01/12345-falsa'
        resultado = adaptar_candidatas(datos, [verificacion()])
        self.assertEqual(resultado['entradas'], [])
        self.assertEqual(resultado['rechazadas'][0]['codigo'], 'url_no_admitida')

    def test_ruta_que_no_corresponde_a_candidata_de_noticia_se_rechaza(self):
        datos = candidato()
        datos['candidatas'][0]['url'] = 'https://www.elterritorio.com.ar/seccion/actualidad'
        resultado = adaptar_candidatas(datos, [verificacion()])
        self.assertEqual(resultado['entradas'], [])
        self.assertEqual(resultado['rechazadas'][0]['codigo'], 'ruta_no_candidata')

    def test_urls_duplicadas_se_cuentan_y_procedencia_no_se_pierde(self):
        datos = candidato()
        datos['candidatas'].append(dict(datos['candidatas'][0], indice=99))
        resultado = adaptar_candidatas(datos, [verificacion()])
        self.assertEqual(resultado['duplicadas'], 1)
        self.assertEqual(len(resultado['entradas']), 1)
        self.assertEqual(resultado['entradas'][0].procedencia['indice_descubrimiento'], 0)

    def test_verificacion_de_otra_url_no_satisface_candidata(self):
        registro = verificacion()
        registro['url'] = 'https://www.elterritorio.com.ar/noticias/2026/10/02/12346-otra-prueba'
        resultado = adaptar_candidatas(candidato(), [registro])
        self.assertEqual(resultado['rechazadas'][0]['codigo'], 'url_no_verificada_como_noticia')

    def test_registros_de_verificacion_duplicados_se_rechazan(self):
        with self.assertRaisesRegex(MetadatosHistoricosInvalidos, 'verificacion_duplicada'):
            adaptar_candidatas(candidato(), [verificacion(), verificacion()])


if __name__ == '__main__':
    unittest.main()
