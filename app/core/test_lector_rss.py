"""Regresiones H2.2: parser real, fixtures locales y prohibición de red."""
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from core.services import lector_rss as lector
from core.services.fuentes_rss import FUENTES_RSS


class LectorRSSTests(SimpleTestCase):
    def setUp(self):
        self.fuente = FUENTES_RSS[0]
        for destino in ('socket.socket.connect', 'socket.socket.connect_ex',
                        'socket.getaddrinfo', 'feedparser.http.get', 'urllib.request.urlopen'):
            parche = patch(destino, side_effect=AssertionError('Red prohibida'))
            parche.start()
            self.addCleanup(parche.stop)

    def fixture(self, nombre):
        return (Path(__file__).parent / 'fixtures' / 'rss' / nombre).read_bytes()

    def feed(self, titulo='Noticia', url='https://misionesonline.net/nota', extra=''):
        from xml.sax.saxutils import escape
        return ('<rss version="2.0"><channel><title>Medio</title><item><title>' + escape(titulo)
                + '</title><link>' + escape(url) + '</link>' + extra
                + '</item></channel></rss>').encode()

    def test_wordpress_namespaces_cdata_y_campos_separados(self):
        resultado = lector.analizar_rss(self.fixture('wordpress.xml'), self.fuente)
        self.assertFalse(resultado.rechazos)
        noticia, = resultado.noticias
        self.assertEqual((noticia.fuente, noticia.fuente_id), ('Misiones Online', 'misiones_online'))
        self.assertEqual(noticia.titulo, 'Educación & salud')
        self.assertEqual(noticia.url, 'https://misionesonline.net/nota?id=42&vista=amp')
        self.assertEqual(noticia.fecha, datetime(2026, 11, 5, 13, 20, 30, tzinfo=timezone.utc))
        self.assertEqual(noticia.resumen, 'Resumen breve.')
        self.assertEqual(noticia.contenido_completo, 'Contenido completo diferente.')
        self.assertEqual(noticia.seccion, 'Sociedad')

    def test_atom_y_content_src_sin_descarga(self):
        resultado = lector.analizar_rss(self.fixture('atom.xml'), self.fuente)
        self.assertFalse(resultado.rechazos)
        noticia, externa = resultado.noticias
        self.assertEqual(noticia.resumen, 'Resumen Atom')
        self.assertEqual(noticia.contenido_completo, 'Artículo completo')
        self.assertEqual(noticia.seccion, 'Política')
        self.assertEqual(externa.contenido_completo, '')
        self.assertIsNone(externa.fecha)

    def test_rdf_resumen_no_es_contenido_completo(self):
        noticia, = lector.analizar_rss(self.fixture('rdf.xml'), self.fuente).noticias
        self.assertEqual(noticia.resumen, 'Sólo resumen')
        self.assertEqual(noticia.contenido_completo, '')
        self.assertEqual(noticia.seccion, 'Locales')

    def test_contenido_sin_resumen_no_lo_inventa(self):
        datos = self.feed(extra='<content:encoded xmlns:content="http://purl.org/rss/1.0/modules/content/"><![CDATA[<p>Completo</p>]]></content:encoded>')
        noticia, = lector.analizar_rss(datos, self.fuente).noticias
        self.assertEqual(noticia.contenido_completo, 'Completo')
        self.assertEqual(noticia.resumen, '')

    def test_18_fuentes_usan_exclusivamente_transporte_seguro(self):
        for fuente in FUENTES_RSS:
            with self.subTest(fuente=fuente.identificador), patch.object(
                lector.descarga_segura, 'descargar', return_value=self.feed(url='https://' + fuente.hosts_permitidos[0] + '/nota')
            ) as descargar:
                resultado = lector.leer_rss(fuente)
                descargar.assert_called_once_with(fuente.feed, fuente=fuente)
                self.assertEqual(resultado.noticias[0].fuente_id, fuente.identificador)

    def test_urls_conservan_query_funcional_escapes_orden_y_duplicados(self):
        casos = {
            'HTTPS://MISIONESONLINE.NET:443/a%2Fb/?id=1&id=2&x=a%20b&UTM_SOURCE=rss&%66bclid=x&ref=portada':
                'https://misionesonline.net/a%2Fb/?id=1&id=2&x=a%20b&ref=portada',
            'https://www.misionesonline.net/a/?feed=rss2&utm_custom=1':
                'https://www.misionesonline.net/a/?feed=rss2&utm_custom=1',
            'https://misionesonline.net/?': 'https://misionesonline.net/?',
        }
        for original, esperado in casos.items():
            self.assertEqual(lector.normalizar_url(original, self.fuente), esperado)

    def test_destinos_invalidos_se_rechazan_por_entrada(self):
        for url in ('http://misionesonline.net/a', 'https://primeraedicion.com.ar/a',
                    'https://127.0.0.1/', 'https://[::1]/', 'https://169.254.169.254/',
                    'https://misionesonline.net.evil.org/', 'https://user@misionesonline.net/',
                    'https://misionesonline.net:8443/', 'https://misionesonline.net/a#fragmento',
                    '/relativa', 'javascript:alert(1)', 'file:///etc/passwd'):
            with self.subTest(url=url):
                resultado = lector.analizar_rss(self.feed(url=url), self.fuente)
                self.assertFalse(resultado.noticias)
                self.assertEqual(len(resultado.rechazos), 1)

    def test_titulos_invalidos_no_se_truncan_y_fecha_no_se_inventa(self):
        for titulo in ('', '   ', 'a' * 256):
            self.assertFalse(lector.analizar_rss(self.feed(titulo=titulo), self.fuente).noticias)
        noticia, = lector.analizar_rss(self.feed(titulo='a' * 255), self.fuente).noticias
        self.assertEqual(len(noticia.titulo), 255)
        self.assertIsNone(noticia.fecha)
        for fecha in ('ayer', '2026', '2026-11-05', '2026-02-30T10:00:00Z',
                      '2026-11-05T10:00:00', 'Thu, 05 Nov 2026 10:00:00', ''):
            with self.subTest(fecha=fecha):
                resultado = lector.analizar_rss(self.feed(extra='<pubDate>' + fecha + '</pubDate>'), self.fuente)
                self.assertFalse(resultado.noticias)
        noticia, = lector.analizar_rss(self.feed(extra='<pubDate>Thu, 05 Nov 2026 10:00:00 -0300</pubDate>'), self.fuente).noticias
        self.assertEqual(noticia.fecha.hour, 13)

    def test_vacios_malformados_y_entrada_invalida_no_oculta_validas(self):
        self.assertEqual(lector.analizar_rss(self.fixture('vacio.xml'), self.fuente).noticias, ())
        for datos in (b'', b'https://evil.org/', b'/etc/passwd', b'<html/>', self.fixture('malformado.xml')):
            with self.subTest(datos=datos), self.assertRaises(ValueError):
                lector.analizar_rss(datos, self.fuente)
        datos = self.feed().replace(b'</channel>', b'<item><title>Sin URL</title></item></channel>')
        resultado = lector.analizar_rss(datos, self.fuente)
        self.assertEqual(len(resultado.noticias), 1)
        self.assertEqual(resultado.rechazos[0][0], 1)

    def test_tamano_limite_entradas_y_politicas_alteradas(self):
        with self.assertRaises(ValueError):
            lector.analizar_rss(b' ' * (self.fuente.max_bytes + 1), self.fuente)
        with self.assertRaises(ValueError):
            lector.analizar_rss('no bytes', self.fuente)
        item = b'<item><title>Nota</title><link>https://misionesonline.net/a</link></item>'
        datos = b'<rss version="2.0"><channel>' + item * 40 + b'</channel></rss>'
        self.assertEqual(len(lector.analizar_rss(datos, self.fuente).noticias), 30)
        for fuente in (replace(self.fuente, max_bytes=self.fuente.max_bytes + 1),
                       replace(self.fuente, hosts_permitidos=self.fuente.hosts_permitidos + ('evil.org',))):
            with patch.object(lector.descarga_segura, 'descargar') as descargar, self.assertRaises(ValueError):
                lector.leer_rss(fuente)
            descargar.assert_not_called()

    def test_entidades_externas_y_xml_base_no_habilitan_red(self):
        datos = b'<!DOCTYPE rss [<!ENTITY externo SYSTEM "http://169.254.169.254/secret">]><rss version="2.0"><channel><item><title>&externo;</title><link>https://misionesonline.net/a</link></item></channel></rss>'
        try:
            resultado = lector.analizar_rss(datos, self.fuente)
        except ValueError:
            pass
        else:
            self.assertFalse(resultado.noticias)
        datos = b'<feed xmlns="http://www.w3.org/2005/Atom" xml:base="https://evil.org/"><title>X</title><entry><title>Nota</title><link href="/a"/></entry></feed>'
        self.assertFalse(lector.analizar_rss(datos, self.fuente).noticias)


    def test_resumen_explicito_identico_a_contenido_se_preserva(self):
        datos = self.feed(extra='<description>Iguales</description><content:encoded xmlns:content="http://purl.org/rss/1.0/modules/content/">Iguales</content:encoded>')
        noticia, = lector.analizar_rss(datos, self.fuente).noticias
        self.assertEqual(noticia.resumen, 'Iguales')
        self.assertEqual(noticia.contenido_completo, 'Iguales')

    def test_dtd_rechazado_incluso_en_utf16(self):
        xml = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE rss [<!ENTITY x "texto">]><rss version="2.0"><channel/></rss>'
        with self.assertRaises(ValueError):
            lector.analizar_rss(xml.encode('utf-16'), self.fuente)

    def atom(self, campos):
        return ('<feed xmlns="http://www.w3.org/2005/Atom"><title>Medio</title><entry>'
                '<link href="https://misionesonline.net/nota"/>' + campos + '</entry></feed>').encode()

    def test_atom_text_literal_en_titulo_resumen_contenido_y_seccion(self):
        datos = self.atom('<title type="text">Uso de &lt;script&gt; en HTML</title>'
                          '<summary type="text">Texto &lt;literal&gt; visible &amp; válido</summary>'
                          '<content type="text">Código &lt;b&gt;literal&lt;/b&gt;</content>'
                          '<category term="Sección &lt;local&gt;"/>')
        noticia, = lector.analizar_rss(datos, self.fuente).noticias
        self.assertEqual(noticia.titulo, 'Uso de <script> en HTML')
        self.assertEqual(noticia.resumen, 'Texto <literal> visible & válido')
        self.assertEqual(noticia.contenido_completo, 'Código <b>literal</b>')
        self.assertEqual(noticia.seccion, 'Sección <local>')

    def test_atom_html_y_xhtml_se_normalizan_como_texto(self):
        for tipo, valor in (
            ('html', '&lt;p&gt;Texto &lt;b&gt;válido&lt;/b&gt;&lt;/p&gt;'),
            ('xhtml', '<div xmlns="http://www.w3.org/1999/xhtml"><p>Texto <b>válido</b></p></div>'),
        ):
            with self.subTest(tipo=tipo):
                datos = self.atom(f'<title type="{tipo}">{valor}</title><summary type="{tipo}">{valor}</summary><content type="{tipo}">{valor}</content>')
                noticia, = lector.analizar_rss(datos, self.fuente).noticias
                self.assertEqual(noticia.titulo, 'Texto válido')
                self.assertEqual(noticia.resumen, 'Texto válido')
                self.assertEqual(noticia.contenido_completo, 'Texto válido')

    def test_rss_titulo_y_categoria_son_literales(self):
        datos = self.feed(titulo='Uso de <script> en HTML', extra='<category>Zona &lt;local&gt;</category>')
        noticia, = lector.analizar_rss(datos, self.fuente).noticias
        self.assertEqual(noticia.titulo, 'Uso de <script> en HTML')
        self.assertEqual(noticia.seccion, 'Zona <local>')

    def test_offsets_invalidos_rfc_e_iso_se_rechazan(self):
        for offset in ('+03:99', '-03:60', '+24:00', '-99:00'):
            for datos in (
                self.atom('<title>Nota</title><published>2026-11-05T10:00:00' + offset + '</published>'),
                self.feed(extra='<pubDate>Thu, 05 Nov 2026 10:00:00 ' + offset.replace(':', '') + '</pubDate>'),
            ):
                with self.subTest(offset=offset, datos=datos):
                    resultado = lector.analizar_rss(datos, self.fuente)
                    self.assertFalse(resultado.noticias)
                    self.assertEqual(len(resultado.rechazos), 1)
        for offset in ('+03:00', '-03:30', '+00:00'):
            datos = self.atom('<title>Nota</title><published>2026-11-05T10:00:00' + offset + '</published>')
            self.assertEqual(len(lector.analizar_rss(datos, self.fuente).noticias), 1)

    def test_contenido_binario_y_codificado_no_es_articulo(self):
        for tipo in ('image/png', 'application/octet-stream', 'application/pdf', 'text/xml'):
            datos = self.atom('<title>Nota</title><content type="' + tipo + '">YWJjZA==</content>')
            with self.subTest(tipo=tipo):
                resultado = lector.analizar_rss(datos, self.fuente)
                self.assertFalse(resultado.noticias)
                self.assertEqual(len(resultado.rechazos), 1)
        for atributo in ('mode="base64"', 'encoding="base64"'):
            datos = self.atom('<title>Nota</title><content type="text/plain" ' + atributo + '>YWJjZA==</content>')
            self.assertFalse(lector.analizar_rss(datos, self.fuente).noticias)
