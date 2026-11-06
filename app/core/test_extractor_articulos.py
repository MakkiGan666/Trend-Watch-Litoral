"""H2.3: fixtures HTML locales y red prohibida, sin ORM ni base de datos."""
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from core.services import extractor_articulos as extractor
from core.services import lector_rss
from core.services.fuentes_rss import FUENTES_RSS


class ExtractorArticulosTests(SimpleTestCase):
    def setUp(self):
        self.fuente = FUENTES_RSS[0]
        self.noticia = lector_rss.NoticiaRSS(
            self.fuente.nombre, self.fuente.identificador, 'Título RSS',
            'https://misionesonline.net/nota', datetime(2026, 11, 1, tzinfo=timezone.utc),
            'Resumen RSS: no es un artículo.', '', 'Locales')
        for destino in ('socket.getaddrinfo', 'socket.socket.connect', 'socket.socket.connect_ex',
                        'urllib.request.urlopen', 'feedparser.http.get'):
            parche = patch(destino, side_effect=AssertionError('Red no autorizada'))
            parche.start()
            self.addCleanup(parche.stop)

    def fixture(self, nombre):
        return (Path(__file__).parent / 'fixtures' / 'articulos' / nombre).read_bytes()

    def analizar(self, datos):
        return extractor.analizar_articulo(datos, self.noticia, self.fuente)

    def test_jsonld_graph_prioridad_y_metadatos(self):
        articulo = self.analizar(self.fixture('jsonld.html'))
        self.assertEqual(articulo.titulo, 'Título JSON-LD')
        self.assertEqual(articulo.url_canonica, 'https://misionesonline.net/noticia?id=7')
        self.assertEqual(articulo.fecha, datetime(2026, 11, 5, 14, 30, tzinfo=timezone.utc))
        self.assertEqual(articulo.imagen_principal, 'https://misionesonline.net/imagenes/nota.jpg')
        self.assertEqual(articulo.cuerpo.count('La comunidad presentó'), 1)
        self.assertTrue(articulo.suficiente)
        self.assertNotIn('Texto secundario', articulo.cuerpo)
        self.assertEqual(articulo.fuente_id, self.fuente.identificador)

    def test_semantica_excluye_ruido_y_repeticiones(self):
        articulo = self.analizar(self.fixture('semantico.html'))
        self.assertEqual(articulo.titulo, 'Nueva biblioteca local')
        self.assertEqual(articulo.imagen_principal, 'https://misionesonline.net/fotos/biblioteca.jpg')
        self.assertEqual(articulo.fecha, datetime(2026, 11, 4, 12, tzinfo=timezone.utc))
        self.assertTrue(articulo.suficiente)
        for ruido in ('Inicio', 'Comprá', 'También', 'relacionada', 'derechos'):
            self.assertNotIn(ruido, articulo.cuerpo)
        self.assertEqual(articulo.cuerpo.count('El equipo organizó'), 1)

    def test_jsonld_array_y_contenedores_compartidos(self):
        articulo = self.analizar(self.fixture('wordpress.html'))
        self.assertEqual(articulo.titulo, 'Título de la nota')
        self.assertIn('propuesta educativa', articulo.cuerpo)
        self.assertNotIn('Contenido ajeno', articulo.cuerpo)
        self.assertEqual(articulo.imagen_principal, 'https://misionesonline.net/fotos/docentes.jpg')
        self.assertEqual(articulo.fecha, datetime(2026, 11, 5, 10, tzinfo=timezone.utc))

    def test_fallback_rss_y_extraccion_insuficiente(self):
        articulo = self.analizar(self.fixture('fallback.html'))
        self.assertEqual((articulo.titulo, articulo.fecha, articulo.url_canonica),
                         (self.noticia.titulo, self.noticia.fecha, self.noticia.url))
        self.assertEqual(articulo.imagen_principal, '')
        self.assertEqual(articulo.cuerpo, 'Información breve.')
        self.assertFalse(articulo.suficiente)
        for datos in (b'', b'<html><body><nav><p>Menu</p></nav></body></html>',
                      b'<html><body><p>Texto general fuera de articulo</p></body></html>'):
            articulo = self.analizar(datos)
            self.assertEqual(articulo.cuerpo, '')
            self.assertFalse(articulo.suficiente)
            self.assertEqual(articulo.titulo, 'Título RSS')

    def test_rechaza_identidad_editorial_de_otro_medio(self):
        with self.assertRaises(ValueError):
            self.analizar(self.fixture('ajeno.html'))
        for etiqueta in ('<meta property="og:url" content="https://evil.org/nota">',
                         '<link rel="canonical" href="https://127.0.0.1/nota">',
                         '<script type="application/ld+json">{"@type":"NewsArticle","url":"https://primeraedicion.com.ar/nota","articleBody":"Texto ajeno"}</script>'):
            with self.subTest(etiqueta=etiqueta), self.assertRaises(ValueError):
                self.analizar(('<html><head>' + etiqueta + '</head><body><article><p>No aceptar</p></article></body></html>').encode())

    def test_imagenes_invalidas_sin_descargas_y_fallback_valido(self):
        for imagen in ('https://evil.org/foto', 'http://misionesonline.net/foto',
                       'https://169.254.169.254/foto', 'https://[::1]/foto',
                       'https://misionesonline.net.evil.org/foto', 'data:image/png;base64,YWJj',
                       'javascript:alert(1)', 'https://user@misionesonline.net/foto',
                       'https://misionesonline.net:8443/foto', 'https://misionesonline.net/foto#x'):
            with self.subTest(imagen=imagen):
                html = f'<html><head><meta property="og:image" content="{imagen}"></head><body><article><img src="/permitida.jpg"></article></body></html>'
                self.assertEqual(self.analizar(html.encode()).imagen_principal, 'https://misionesonline.net/permitida.jpg')

    def test_url_canonica_conservadora_e_ignora_base_y_recursos(self):
        html = b'<html><head><base href="https://evil.org/"><link rel="canonical" href="/nota?id=1&amp;id=2&amp;utm_source=x&amp;vista=amp"><script src="https://evil.org/a.js"></script></head><body><article><img src="/foto.jpg"><iframe src="http://169.254.169.254/"></iframe></article></body></html>'
        articulo = self.analizar(html)
        self.assertEqual(articulo.url_canonica, 'https://misionesonline.net/nota?id=1&id=2&vista=amp')
        self.assertEqual(articulo.imagen_principal, 'https://misionesonline.net/foto.jpg')

    def test_datos_invalidos_no_reemplazan_fallback_rss(self):
        for fecha in ('ayer', '2026-11-05', '2026-02-30T12:00:00Z', '2026-11-05T12:00:00+03:99'):
            html = ('<html><head><meta property="article:published_time" content="' + fecha
                    + '"><meta property="og:title" content="' + 'x' * 256 + '"></head></html>')
            articulo = self.analizar(html.encode())
            self.assertEqual(articulo.fecha, self.noticia.fecha)
            self.assertEqual(articulo.titulo, self.noticia.titulo)
        articulo = extractor.analizar_articulo(b'<html/>', replace(self.noticia, fecha=None), self.fuente)
        self.assertIsNone(articulo.fecha)

    def test_titulo_literal_sin_truncar_y_h1_como_fallback(self):
        html = b'<html><article><h1>Uso de &lt;script&gt; en HTML</h1></article></html>'
        self.assertEqual(self.analizar(html).titulo, 'Uso de <script> en HTML')
        self.assertEqual(self.analizar(b'<html><article><h1>' + b'x' * 256 + b'</h1></article></html>').titulo, self.noticia.titulo)

    def test_18_fuentes_una_descarga_por_articulo(self):
        for fuente in FUENTES_RSS:
            noticia = replace(self.noticia, fuente=fuente.nombre, fuente_id=fuente.identificador,
                              url='https://' + fuente.hosts_permitidos[0] + '/nota')
            with self.subTest(fuente=fuente.identificador), patch.object(
                extractor.descarga_segura, 'descargar', return_value=b'<html><article><p>Texto breve.</p></article></html>'
            ) as descargar:
                articulo = extractor.extraer_articulo(noticia)
                descargar.assert_called_once_with(noticia.url, fuente=fuente)
                self.assertEqual(articulo.fuente_id, fuente.identificador)

    def test_integracion_con_noticia_real_de_lector_h22(self):
        datos = (Path(__file__).parent / 'fixtures' / 'rss' / 'wordpress.xml').read_bytes()
        noticia, = lector_rss.analizar_rss(datos, self.fuente).noticias
        with patch.object(extractor.descarga_segura, 'descargar', return_value=self.fixture('semantico.html')) as descargar:
            articulo = extractor.extraer_articulo(noticia)
            descargar.assert_called_once_with(noticia.url, fuente=self.fuente)
            self.assertTrue(articulo.suficiente)

    def test_politicas_y_noticias_manipuladas_rechazadas_antes_de_descargar(self):
        casos = ((self.noticia, replace(self.fuente, max_bytes=self.fuente.max_bytes + 1)),
                 (self.noticia, replace(self.fuente, hosts_permitidos=self.fuente.hosts_permitidos + ('evil.org',))),
                 (replace(self.noticia, url='https://primeraedicion.com.ar/a'), self.fuente),
                 (replace(self.noticia, fuente_id='otra'), self.fuente),
                 (replace(self.noticia, fecha=datetime(2026, 11, 5)), self.fuente))
        for noticia, fuente in casos:
            with self.subTest(noticia=noticia), patch.object(extractor.descarga_segura, 'descargar') as descargar:
                with self.assertRaises(ValueError):
                    extractor.extraer_articulo(noticia, fuente)
                descargar.assert_not_called()

    def test_limites_y_html_malformado(self):
        for datos in (b'x' * (self.fuente.max_bytes + 1), b'<div>' * 130,
                      b'<br>' * 30001, b'<meta charset="utf-7">', b'\xff\xff', 'no bytes'):
            with self.subTest(datos=str(datos)[:60]), self.assertRaises(ValueError):
                self.analizar(datos)
        articulo = self.analizar(b'<html><article><h1>Nota</h1><p>Un parrafo sin cerrar')
        self.assertEqual(articulo.titulo, 'Nota')
        self.assertEqual(articulo.cuerpo, 'Un parrafo sin cerrar')

    def test_jsonld_invalido_o_ambiguo_no_inventa_articulo(self):
        for contenido in ('{roto}', '42', 'null',
                          '[{"@type":"Article","headline":"Uno"},{"@type":"NewsArticle","headline":"Dos"}]'):
            html = '<html><head><script type="application/ld+json">' + contenido + '</script></head></html>'
            articulo = self.analizar(html.encode())
            self.assertEqual(articulo.titulo, self.noticia.titulo)
            self.assertEqual(articulo.cuerpo, '')


    def test_h1_en_cabecera_del_articulo_con_cuerpo_separado(self):
        html = b'<html><body><nav><h1>Menu</h1></nav><article><header><h1>Titulo semantico</h1></header><div class="entry-content"><p>Texto de la noticia.</p></div></article></body></html>'
        articulo = self.analizar(html)
        self.assertEqual(articulo.titulo, 'Titulo semantico')
        self.assertEqual(articulo.cuerpo, 'Texto de la noticia.')

    def test_jsonld_fecha_imagen_y_titulo_invalidos_caen_a_og(self):
        html = b'<html><head><script type="application/ld+json">{"@type":"NewsArticle","headline":42,"datePublished":"ayer","image":{"url":"https://evil.org/foto"}}</script><meta property="og:title" content="Titulo OG"><meta property="og:image" content="/foto.jpg"><meta property="article:published_time" content="2026-11-05T13:00:00Z"></head><body></body></html>'
        articulo = self.analizar(html)
        self.assertEqual(articulo.titulo, 'Titulo OG')
        self.assertEqual(articulo.imagen_principal, 'https://misionesonline.net/foto.jpg')
        self.assertEqual(articulo.fecha, datetime(2026, 11, 5, 13, tzinfo=timezone.utc))

    def test_contenedores_especificos_sin_article_ni_main(self):
        for selector in ('class="entry-content"', 'class="td-post-content"',
                         'class="article-body"', 'itemprop="articleBody"'):
            with self.subTest(selector=selector):
                datos = ('<html><body><div ' + selector + '><p>Cuerpo válido de la noticia.</p></div></body></html>').encode()
                self.assertEqual(self.analizar(datos).cuerpo, 'Cuerpo válido de la noticia.')
        datos = b'<html><main><p>Ruido exterior.</p><div class="entry-content"><p>Cuerpo especifico.</p></div></main></html>'
        self.assertEqual(self.analizar(datos).cuerpo, 'Cuerpo especifico.')

    def test_canonica_invalida_no_oculta_identidad_jsonld_ajena(self):
        import json
        for canonica in ('javascript:alert(1)', '/nota', 'https://[invalida'):
            for identidad in (
                {'url': 'https://primeraedicion.com.ar/otra'},
                {'mainEntityOfPage': {'@id': 'https://primeraedicion.com.ar/otra'}},
                {'url': 'https://primeraedicion.com.ar/otra', 'mainEntityOfPage': {'@id': self.noticia.url}},
            ):
                articulo = {'@type': 'NewsArticle', **identidad}
                html = ('<html><head><link rel="canonical" href="' + canonica
                        + '"><script type="application/ld+json">' + json.dumps(articulo)
                        + '</script></head><body><article><p>Texto ajeno.</p></article></body></html>')
                with self.subTest(canonica=canonica, identidad=identidad), self.assertRaises(ValueError):
                    self.analizar(html.encode())
        for url in ('javascript:alert(1)', 'http://misionesonline.net/nota', 'data:text/plain,nota'):
            html = ('<html><head><link rel="canonical" href="/nota">'
                    '<script type="application/ld+json">'
                    + json.dumps({'@type': 'Article', 'url': url}) + '</script></head></html>')
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.analizar(html.encode())

    def test_jsonld_inerte_oculto_o_recomendado_no_suplanta_articulo(self):
        import json
        falso = json.dumps({'@type': 'NewsArticle', 'url': self.noticia.url,
                            'headline': 'Recomendación oculta',
                            'articleBody': 'Texto ajeno a la noticia principal. ' * 20})
        for apertura, cierre in (
            ('<template>', '</template>'), ('<div hidden>', '</div>'),
            ('<div aria-hidden="true">', '</div>'),
            ('<div style="display: none !important">', '</div>'),
            ('<div style="visibility:hidden">', '</div>'),
            ('<div class="related-posts">', '</div>'), ('<nav>', '</nav>'),
            ('<aside>', '</aside>'), ('<div class="publicidad"><section>', '</section></div>'),
        ):
            html = ('<html><body>' + apertura + '<script type="application/ld+json">' + falso
                    + '</script>' + cierre + '<article><h1>Artículo principal</h1>'
                    '<p>Cuerpo principal real.</p></article></body></html>')
            with self.subTest(apertura=apertura):
                articulo = self.analizar(html.encode())
                self.assertEqual(articulo.titulo, 'Artículo principal')
                self.assertEqual(articulo.cuerpo, 'Cuerpo principal real.')
                self.assertFalse(articulo.suficiente)
        # El propio script también puede estar oculto, sin ancestros ocultos.
        html = '<html><script hidden type="application/ld+json">' + falso + '</script></html>'
        self.assertEqual(self.analizar(html.encode()).titulo, self.noticia.titulo)

    def test_jsonld_insuficiente_recupera_html_suficiente(self):
        texto = ('Los vecinos participaron de una reunión abierta para conocer los proyectos '
                 'educativos de la ciudad y discutir sus próximas actividades comunitarias.')
        for cuerpo_json in ('Breve.', '   ', 'x' * 130):
            html = ('<html><head><script type="application/ld+json">'
                    '{"@type":"NewsArticle","headline":"Título JSON","articleBody":"'
                    + cuerpo_json + '"}</script></head><body><article><p>' + texto
                    + '</p></article></body></html>')
            articulo = self.analizar(html.encode())
            self.assertEqual(articulo.cuerpo, texto)
            self.assertEqual(articulo.titulo, 'Título JSON')
            self.assertTrue(articulo.suficiente)
        html = b'<html><head><script type="application/ld+json">{"@type":"Article","articleBody":"Breve."}</script></head><body><article><p>Otro texto breve.</p></article></body></html>'
        self.assertFalse(self.analizar(html).suficiente)

    def test_blockquote_con_parrafos_anidados_no_duplica_texto(self):
        datos = b'<html><article><blockquote>Antes.<p>Primera frase citada.</p><p>Segunda frase citada.</p>Despues.</blockquote><p>Parrafo final.</p></article></html>'
        cuerpo = self.analizar(datos).cuerpo
        self.assertEqual(cuerpo, 'Antes. Primera frase citada. Segunda frase citada. Despues.\n\nParrafo final.')
        for frase in ('Primera frase citada.', 'Segunda frase citada.'):
            self.assertEqual(cuerpo.count(frase), 1)
        datos = b'<html><article><blockquote>Cita directa.</blockquote><blockquote><blockquote><p>Cita anidada.</p></blockquote></blockquote></article></html>'
        self.assertEqual(self.analizar(datos).cuerpo, 'Cita directa.\n\nCita anidada.')

    def test_errores_estructurados_conservan_valueerror(self):
        import json

        casos = (
            ('IDENTIDAD_EDITORIAL', b'<meta property="og:url" content="https://primeraedicion.com.ar/a">'),
            ('URL_CANONICA', b'<link rel="canonical" href="https://primeraedicion.com.ar/a">'),
            ('JSONLD', ('<script type="application/ld+json">' + json.dumps({
                '@type': 'NewsArticle', 'url': 'https://misionesonline.net/otra',
                'articleBody': 'Texto que no coincide con la URL RSS.',
            }) + '</script>').encode()),
            ('CODIFICACION', b'<meta charset="utf-7">'),
            ('CODIFICACION', b'<meta charset="utf-8"><p>\xff</p>'),
            ('LIMITE_PROCESAMIENTO', b'<br>' * 30001),
        )
        for codigo, etiqueta in casos:
            with self.subTest(codigo=codigo), self.assertRaises(ValueError) as contexto:
                self.analizar(b'<html><head>' + etiqueta + b'</head><body><article><p>Texto de prueba.</p></article></body></html>')
            self.assertEqual(contexto.exception.codigo, codigo)
            self.assertIsInstance(contexto.exception.metricas, dict)
        with self.assertRaises(ValueError) as contexto:
            extractor.analizar_articulo('no son bytes', self.noticia, self.fuente)
        self.assertEqual(contexto.exception.codigo, 'HTML_INVALIDO')
        with self.assertRaises(ValueError) as contexto:
            extractor.analizar_articulo(b'x' * (self.fuente.max_bytes + 1), self.noticia, self.fuente)
        self.assertEqual(contexto.exception.codigo, 'LIMITE_PROCESAMIENTO')

    def test_diagnostico_es_resumido_y_no_incluye_contenido(self):
        html = (b'<html><meta charset="utf-8"><script type="application/ld+json">{roto}</script>'
                b'<article><div class="entry-content"><p>Contenido de prueba que no debe aparecer en el resumen.</p>'
                b'<p>Segundo bloque de prueba para medir longitud sin conservar sus palabras.</p></div></article></html>')
        diagnostico = extractor.diagnosticar_articulo(html, self.noticia, self.fuente)
        self.assertEqual(diagnostico['estado'], 'analizado')
        metricas = diagnostico['metricas']
        self.assertEqual(metricas['hostname'], 'misionesonline.net')
        self.assertEqual(metricas['charset'], 'utf-8')
        self.assertGreater(metricas['nodos_html'], 0)
        self.assertEqual(metricas['scripts_jsonld'], 1)
        self.assertEqual(metricas['candidatos_jsonld'], 0)
        self.assertEqual(metricas['jsonld_invalidos'], 1)
        self.assertGreater(metricas['longitudes_contenedores'][0]['caracteres'], 0)
        resumen = repr(diagnostico)
        for dato in ('Contenido de prueba', 'Segundo bloque', self.noticia.url, self.noticia.titulo):
            self.assertNotIn(dato, resumen)

    def test_canonica_insegura_se_mide_sin_cambiar_el_fallback(self):
        articulo = extractor.analizar_articulo(
            b'<link rel="canonical" href="javascript:alert(1)"><article><p>Texto breve.</p></article>',
            self.noticia, self.fuente,
        )
        self.assertEqual(articulo.url_canonica, self.noticia.url)

    def test_diagnostico_identidad_jsonld_coincide_con_rss_y_canonical(self):
        import json
        html = ('<link rel="canonical" href="/canonica">'
                '<script type="application/ld+json">' + json.dumps({
                    '@type': 'NewsArticle', 'url': 'https://misionesonline.net/canonica',
                    'mainEntityOfPage': {'@id': self.noticia.url},
                }) + '</script><article><p>Texto breve.</p></article>').encode()
        diagnostico = extractor.diagnosticar_articulo(html, self.noticia, self.fuente)
        self.assertEqual(diagnostico['estado'], 'analizado')
        metricas = diagnostico['metricas']
        self.assertFalse(metricas['canonical_coincide_url_rss'])
        self.assertEqual(metricas['subcodigos_relacion_canonical'], ['CANONICAL_NO_COINCIDE_URL_RSS'])
        identidad = metricas['identidades_jsonld'][0]
        self.assertTrue(identidad['url']['coincide_canonical'])
        self.assertTrue(identidad['mainEntityOfPage']['coincide_url_rss'])
        self.assertTrue(identidad['url']['hostname_permitido'])
        self.assertNotIn(self.noticia.url, repr(diagnostico))

    def test_diagnostico_distingue_url_y_mainentity_que_no_coinciden(self):
        import json
        casos = (
            ('url', {'url': 'https://misionesonline.net/otra',
                     'mainEntityOfPage': {'@id': self.noticia.url}},
             'JSONLD_URL_NO_COINCIDE_RSS_NI_CANONICAL'),
            ('mainEntityOfPage', {'url': self.noticia.url,
                                  'mainEntityOfPage': {'@id': 'https://misionesonline.net/otra'}},
             'JSONLD_MAIN_ENTITY_OF_PAGE_NO_COINCIDE_RSS_NI_CANONICAL'),
        )
        for campo, identidad, esperado in casos:
            with self.subTest(campo=campo):
                articulo = {'@type': 'NewsArticle', **identidad}
                html = ('<link rel="canonical" href="/canonica">'
                        '<script type="application/ld+json">' + json.dumps(articulo)
                        + '</script><article><p>Texto breve.</p></article>').encode()
                diagnostico = extractor.diagnosticar_articulo(html, self.noticia, self.fuente)
                self.assertEqual(diagnostico['codigo'], 'JSONLD')
                self.assertEqual(diagnostico['subcodigo'], esperado)
                comparacion = diagnostico['metricas']['identidades_jsonld'][0]
                self.assertTrue(comparacion['url']['campo_presente'])
                self.assertTrue(comparacion['mainEntityOfPage']['campo_presente'])
                self.assertNotIn('https://misionesonline.net/', repr(diagnostico))

    def test_diagnostico_host_jsonld_ajeno_solo_registra_denegacion(self):
        import json
        articulo = {'@type': 'NewsArticle', 'url': 'https://example.invalid/nota'}
        html = ('<script type="application/ld+json">' + json.dumps(articulo)
                + '</script><article><p>Texto breve.</p></article>').encode()
        diagnostico = extractor.diagnosticar_articulo(html, self.noticia, self.fuente)
        self.assertEqual(diagnostico['codigo'], 'IDENTIDAD_EDITORIAL')
        self.assertEqual(diagnostico['subcodigo'], 'JSONLD_URL_HOST_NO_PERMITIDO')
        self.assertFalse(diagnostico['metricas']['hostname_declarado_permitido'])
        self.assertNotIn('example.invalid', repr(diagnostico))
        self.assertNotIn('url', diagnostico['metricas'])

    def test_jsonld_acepta_fragmento_solo_si_coincide_con_rss_o_canonical(self):
        import json
        casos_validos = (
            ('https://misionesonline.net/nota#principal', 'https://misionesonline.net/canonica'),
            ('https://misionesonline.net/canonica#principal', 'https://misionesonline.net/canonica'),
        )
        for identidad, canonical in casos_validos:
            with self.subTest(identidad=identidad, canonical=canonical):
                html = ('<link rel="canonical" href="' + canonical + '">'
                        '<script type="application/ld+json">' + json.dumps({
                            '@type': 'NewsArticle', 'url': self.noticia.url,
                            'mainEntityOfPage': {'@id': identidad},
                        }) + '</script><article><p>Texto breve.</p></article>').encode()
                articulo = self.analizar(html)
                diagnostico = extractor.diagnosticar_articulo(
                    html, self.noticia, self.fuente)
                self.assertEqual(articulo.url_canonica, canonical)
                self.assertTrue(
                    diagnostico['metricas']['identidades_jsonld'][0]
                    ['mainEntityOfPage']['coincide_por_fragmento']
                )
                self.assertFalse(
                    diagnostico['metricas']['identidades_jsonld'][0]
                    ['mainEntityOfPage']['estructura']['rss']['normalizable']
                )
                self.assertNotIn('#principal', repr(diagnostico))

    def test_jsonld_fragmento_no_acepta_host_path_query_ni_puerto_ajenos(self):
        import json
        casos = (
            ('https://evil.invalid/nota#x', 'IDENTIDAD_EDITORIAL'),
            ('https://misionesonline.net/otra#x', 'JSONLD'),
            ('https://misionesonline.net/nota?edicion=2#x', 'JSONLD'),
            ('https://user@misionesonline.net/nota#x', 'JSONLD'),
            ('https://misionesonline.net:8443/nota#x', 'JSONLD'),
            ('http://misionesonline.net/nota#x', 'JSONLD'),
        )
        for identidad, codigo in casos:
            with self.subTest(identidad=identidad):
                html = ('<script type="application/ld+json">' + json.dumps({
                    '@type': 'NewsArticle', 'url': self.noticia.url,
                    'mainEntityOfPage': {'@id': identidad},
                }) + '</script><article><p>Texto breve.</p></article>').encode()
                with self.assertRaises(ValueError) as contexto:
                    self.analizar(html)
                self.assertEqual(contexto.exception.codigo, codigo)

    def test_graph_masivo_conserva_primer_subcodigo_y_metricas_acotadas(self):
        import json
        candidatos = []
        for indice in range(80):
            if indice == 0:
                candidatos.append({
                    '@type': 'NewsArticle',
                    'url': 'https://misionesonline.net/otra',
                    'mainEntityOfPage': {'@id': self.noticia.url},
                })
            else:
                candidatos.append({
                    '@type': 'NewsArticle',
                    'url': self.noticia.url,
                    'mainEntityOfPage': {'@id': f'https://misionesonline.net/otra-{indice}'},
                })
        html = ('<link rel="canonical" href="/canonica">'
                '<script type="application/ld+json">' + json.dumps({'@graph': candidatos})
                + '</script><article><p>Texto breve.</p></article>').encode()

        diagnostico = extractor.diagnosticar_articulo(html, self.noticia, self.fuente)

        self.assertEqual(diagnostico['codigo'], 'JSONLD')
        self.assertEqual(diagnostico['subcodigo'], 'JSONLD_URL_NO_COINCIDE_RSS_NI_CANONICAL')
        metricas = diagnostico['metricas']
        self.assertEqual(metricas['candidatos_jsonld'], 80)
        self.assertEqual(len(metricas['identidades_jsonld']), 10)
        self.assertEqual(metricas['identidades_jsonld_truncadas'], 70)
        self.assertNotIn('subcodigos_jsonld', metricas)
        self.assertLess(len(repr(metricas)), 30000)

    def test_comparaciones_estructurales_url_no_exponen_valores(self):
        import json

        def medir(identidad, canonical=None):
            articulo = {'@type': 'NewsArticle', 'mainEntityOfPage': {'@id': identidad}}
            cabeza = (f'<link rel="canonical" href="{canonical}">' if canonical else '')
            html = (cabeza + '<script type="application/ld+json">'
                    + json.dumps(articulo) + '</script><article><p>Texto breve.</p></article>').encode()
            return extractor.diagnosticar_articulo(html, self.noticia, self.fuente)

        casos = (
            ('https://misionesonline.net/nota/', None, 'barra_final'),
            ('https://www.misionesonline.net/nota', None, 'www'),
            ('https://misionesonline.net/nota?vista=amp', None, 'query_funcional'),
        )
        for identidad, canonical, tipo in casos:
            with self.subTest(tipo=tipo):
                diagnostico = medir(identidad, canonical)
                estructura = diagnostico['metricas']['identidades_jsonld'][0][
                    'mainEntityOfPage']['estructura']['rss']
                self.assertTrue(estructura['normalizable'])
                referencia = estructura['referencia']
                if tipo == 'barra_final':
                    self.assertFalse(referencia['path_exacto'])
                    self.assertTrue(referencia['path_igual_sin_barra_final'])
                elif tipo == 'www':
                    self.assertTrue(estructura['hostname_permitido'])
                    self.assertFalse(referencia['hostname_exacto'])
                else:
                    self.assertFalse(referencia['query_exacta'])
                    self.assertFalse(referencia['query_igual_sin_tracking'])
                    self.assertFalse(referencia['query_difiere_solo_tracking'])
                self.assertTrue(all(
                    isinstance(valor, bool)
                    for valor in _valores_hoja(estructura)
                ))
                for dato in (identidad, 'vista=amp'):
                    self.assertNotIn(dato, repr(diagnostico))

        tracking = medir('https://misionesonline.net/nota?utm_source=campania')
        estructura = tracking['metricas']['identidades_jsonld'][0][
            'mainEntityOfPage']['estructura']['rss']
        self.assertTrue(estructura['normalizable'])
        self.assertFalse(estructura['referencia']['query_exacta'])
        self.assertTrue(estructura['referencia']['query_igual_sin_tracking'])
        self.assertTrue(estructura['referencia']['query_difiere_solo_tracking'])
        self.assertTrue(tracking['metricas']['identidades_jsonld'][0][
            'mainEntityOfPage']['coincide_url_rss'])
        self.assertNotIn('campania', repr(tracking))

        con_fragmento = medir(self.noticia.url + '#seccion')
        estructura = con_fragmento['metricas']['identidades_jsonld'][0][
            'mainEntityOfPage']['estructura']['rss']
        self.assertFalse(estructura['normalizable'])
        self.assertTrue(estructura['fragmento_presente'])
        self.assertFalse(estructura['referencia']['normaliza_igual'])
        self.assertFalse(estructura['referencia']['fragmento_igual'])

        casos_no_validos = (
            ('http://misionesonline.net/nota', 'esquema_https'),
            ('https://misionesonline.net:8443/nota', 'puerto_permitido'),
            ('https://misionesonline.net:0/nota', 'puerto_permitido'),
            ('https://usuario:secreto@misionesonline.net/nota', 'sin_credenciales'),
        )
        for identidad, bandera in casos_no_validos:
            with self.subTest(bandera=bandera):
                diagnostico = medir(identidad)
                estructura = diagnostico['metricas']['identidades_jsonld'][0][
                    'mainEntityOfPage']['estructura']['rss']
                self.assertFalse(estructura['normalizable'])
                self.assertFalse(estructura[bandera])
                self.assertNotIn(identidad, repr(diagnostico))


def _valores_hoja(valor):
    if isinstance(valor, dict):
        for hijo in valor.values():
            yield from _valores_hoja(hijo)
    else:
        yield valor
