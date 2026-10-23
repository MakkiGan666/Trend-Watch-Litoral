from datetime import datetime, timezone
from html import escape
from unittest.mock import patch

from django.test import TestCase, SimpleTestCase
from django.urls import reverse
from django.utils import timezone as django_timezone

from core.models import Publicacion
from core.presentacion_busqueda import imagen_segura, segmentos_resaltados


class PresentacionBusquedaTests(SimpleTestCase):
    def test_acentos_enie_nfd_y_expansion(self):
        texto = 'İ EDUCACIÓN niño nino educacio\u0301n'
        partes = segmentos_resaltados(texto, ['i\u0307', 'educacion', 'niño'])
        marcados = [p['texto'] for p in partes if p['coincide']]
        self.assertEqual(marcados, ['İ', 'EDUCACIÓN', 'niño', 'educación'])
        self.assertEqual(''.join(p['texto'] for p in partes), 'İ EDUCACIÓN niño nino educación')

    def test_superpuestos_y_repetidos(self):
        self.assertEqual(segmentos_resaltados('banana', ['ana', 'ana']),
                         [{'texto': 'b', 'coincide': False}, {'texto': 'anana', 'coincide': True}])
        self.assertEqual(segmentos_resaltados('educación', ['educ', 'cacion']),
                         [{'texto': 'educación', 'coincide': True}])
        self.assertEqual(segmentos_resaltados('Texto', ['ausente']), [{'texto': 'Texto', 'coincide': False}])

    def test_protocolos_de_imagen(self):
        for url in ['/media/foto.jpg', '/static/img/a%20b.png', 'https://medio.invalid/foto.jpg', 'http://medio.invalid/a']:
            self.assertEqual(imagen_segura(url), url)
        for url in ['javascript:alert(1)', 'data:image/svg+xml,x', '//medio.invalid/x', '/%2fmedio.invalid/x',
                    '/\\medio.invalid/x', 'https://user:pass@medio.invalid/x', 'http://[mal',
                    '/foto%0a.jpg', 'https://medio.invalid/ foto', 'file:///etc/passwd', None]:
            with self.subTest(url=url): self.assertIsNone(imagen_segura(url))


class BusquedaHTMLTests(TestCase):
    def crear(self, titulo='Educación en Misiones', contenido='Propuesta educativa para la provincia.', **datos):
        return Publicacion.objects.create(hash_origen=str(Publicacion.objects.count()), titulo=titulo,
                                          contenido=contenido, **datos)

    def get(self, q=None, **datos):
        if q is not None: datos['q'] = q
        return self.client.get(reverse('buscar_noticias'), datos)

    def test_inicial_sin_listar(self):
        self.crear(titulo='No mostrar esta noticia')
        for q in [None, '', ' \t\n\u00a0']:
            with self.assertNumQueries(0): respuesta = self.get(q)
            self.assertEqual(respuesta.status_code, 200)
            self.assertContains(respuesta, 'Buscá en las noticias del Litoral')
            self.assertNotContains(respuesta, 'No mostrar esta noticia')
            self.assertContains(respuesta, 'method="get"')
            self.assertContains(respuesta, 'data-search-fallback')

    def test_contenido_anonimo_sin_escrituras_ni_http(self):
        p = self.crear(titulo='Una propuesta provincial', contenido='Educación y oportunidades')
        with patch('requests.sessions.Session.request', side_effect=AssertionError('HTTP externo')), \
             self.assertNumQueries(2):
            respuesta = self.get('educacion')
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, reverse('noticia', args=[p.pk]))
        self.assertContains(respuesta, '<mark>Educación</mark>', html=False)
        self.assertContains(respuesta, '1 noticia para')
        self.assertNotContains(respuesta, 'procesar-sentimiento')
        self.assertNotContains(respuesta, 'publicaciones/crear')

    def test_errores_conservan_texto_y_estado_vacio(self):
        for consulta in ['a', 'x'*151, '\x0b']:
            respuesta = self.get(consulta)
            self.assertEqual(respuesta.status_code, 400)
            self.assertContains(respuesta, 'id="search-error"', status_code=400)
        self.crear()
        for pagina in ['0', '-1', 'abc', '2']:
            respuesta = self.get('educacion', page=pagina)
            self.assertEqual(respuesta.status_code, 400)
            self.assertContains(respuesta, 'value="educacion"', status_code=400)
        respuesta = self.get('ausente')
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'No encontramos noticias')
        self.assertNotContains(respuesta, 'id="search-error"')

    def test_paginacion_compacta_preserva_q(self):
        Publicacion.objects.bulk_create([Publicacion(hash_origen=str(i), titulo='Educación 50%', contenido='texto') for i in range(43)])
        respuesta = self.get('  EDUCACION 50%  ')
        self.assertEqual(len(respuesta.context['resultados']), 20)
        self.assertContains(respuesta, 'q=EDUCACION+50%25&amp;page=2')
        segunda = self.client.get(respuesta.context['siguiente'])
        self.assertEqual(segunda.context['pagina'].number, 2)
        self.assertContains(segunda, 'value="EDUCACION 50%"')
        self.assertContains(segunda, 'Página 2 de 3')
        self.assertNotContains(respuesta, 'page=3')

    def test_html_escapado_en_consulta_titulo_y_extracto(self):
        titulo = '<svg/onload=alert(1)> Educación'
        self.crear(titulo=titulo, contenido='Texto &lt;img src=x onerror=alert(1)&gt; educación')
        respuesta = self.get('<svg/onload=alert(1)>')
        self.assertContains(respuesta, '&lt;svg/onload=alert(1)&gt;')
        self.assertNotContains(respuesta, '<svg/onload=alert(1)>')
        self.assertNotContains(respuesta, '<img src=x')
        respuesta = self.get('educacion')
        self.assertContains(respuesta, '<mark>Educación</mark>')
        self.assertContains(respuesta, '&lt;img src=x onerror=alert(1)&gt;')
        self.assertNotContains(respuesta, '<img src=x')

    def test_fechas_fuente_e_imagen(self):
        fecha = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
        self.crear(fecha_captura=fecha, imagen_url='javascript:alert(1)', fuente='<b>Fuente</b>')
        respuesta = self.get('educacion')
        self.assertContains(respuesta, 'Capturada el')
        self.assertContains(respuesta, 'datetime="2026-10-23T09:00:00-03:00"')
        self.assertContains(respuesta, '&lt;b&gt;Fuente&lt;/b&gt;')
        self.assertNotContains(respuesta, 'javascript:')
        self.crear(fecha_publicacion=fecha, imagen_url='/media/foto.jpg', fuente='El Territorio (Archivo)')
        respuesta = self.get('educacion')
        self.assertContains(respuesta, 'Publicada el')
        self.assertContains(respuesta, 'datetime="2026-10-23"')
        self.assertContains(respuesta, 'src="/media/foto.jpg"')

    def test_navegaciones_y_metodos(self):
        for url in ['landing', 'categorias', 'litoral']:
            respuesta = self.client.get(reverse(url), follow=True)
            self.assertEqual(respuesta.status_code, 200)
            self.assertContains(respuesta, 'aria-controls="public-search-row"', count=1)
            self.assertContains(respuesta, 'id="public-search-row"', count=1)
        self.assertEqual(self.client.get(reverse('login')).status_code, 302)
        for metodo in ['post', 'put', 'delete', 'head']:
            self.assertEqual(getattr(self.client, metodo)(reverse('buscar_noticias')).status_code, 405)

    def test_no_oculta_error_interno(self):
        with patch('core.views_buscador.buscar', side_effect=RuntimeError('Error interno')):
            with self.assertRaises(RuntimeError): self.get('educacion')
