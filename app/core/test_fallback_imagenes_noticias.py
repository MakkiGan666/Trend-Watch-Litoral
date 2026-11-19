from django.test import TestCase
from django.template.loader import render_to_string
from django.urls import reverse

from core.models import Publicacion


class FallbackImagenesNoticiasTests(TestCase):
    def crear_publicacion(self, *, imagen_url='', completa=True, titulo='Incendio controlado en Misiones'):
        return Publicacion.objects.create(
            hash_origen=f'fallback-{Publicacion.objects.count()}-{titulo}',
            fuente='El Territorio (Misiones)', titulo=titulo,
            contenido=('La información editorial de la noticia se presenta en esta prueba aislada.'
                       if completa else ''),
            contenido_completo=completa, url='https://www.elterritorio.com.ar/noticia-prueba',
            imagen_url=imagen_url,
        )

    def test_tarjetas_regionales_y_etiquetas_preparan_fallback_si_falla_la_url(self):
        publicacion = self.crear_publicacion(imagen_url='https://imagenes.invalid/foto.jpg')
        for plantilla in ('partials/_regional_card.html', 'partials/_etiqueta_news_card.html'):
            with self.subTest(plantilla=plantilla):
                html = render_to_string(plantilla, {'publicacion': publicacion})
                self.assertIn('data-news-image-container', html)
                self.assertIn('data-news-image-fallback', html)
                self.assertIn('data-news-image-placeholder', html)
                self.assertIn('hidden', html)

    def test_tarjeta_sin_url_muestra_fallback_sin_crear_img(self):
        publicacion = self.crear_publicacion()
        html = render_to_string('partials/_regional_card.html', {'publicacion': publicacion})
        self.assertIn('data-news-image-placeholder', html)
        self.assertNotIn('<img', html)

    def test_tarjetas_de_tendencias_y_rankings_comparten_el_mismo_estado(self):
        publicacion = self.crear_publicacion(imagen_url='https://imagenes.invalid/foto.jpg')
        tendencia = {
            'publicacion': publicacion, 'cobertura': False, 'previa': True,
            'tema': 'Misiones', 'publicaciones_24h': 0, 'participaciones': 1,
        }
        html_tendencia = render_to_string('partials/_tendencia_card.html', {
            'tendencia': tendencia, 'numero': 1, 'destacada': False,
        })
        html_ranking = render_to_string('partials/_ranking_card.html', {
            'publicacion': publicacion, 'ejemplo': True, 'tipo': 'positivo',
        })
        for html in (html_tendencia, html_ranking):
            with self.subTest(fragmento=html[:40]):
                self.assertIn('data-news-image-container', html)
                self.assertIn('data-news-image-fallback', html)
                self.assertIn('data-news-image-placeholder', html)

    def test_detalle_tiene_fallback_para_url_fallida_y_sin_imagen(self):
        con_imagen = self.crear_publicacion(imagen_url='https://imagenes.invalid/foto.jpg')
        html = self.client.get(reverse('noticia', args=[con_imagen.pk])).content.decode()
        self.assertIn('data-news-image-container', html)
        self.assertIn('data-news-image-credit', html)
        self.assertIn('data-news-image-placeholder hidden', html)

        sin_imagen = self.crear_publicacion(titulo='Sin imagen de noticia')
        html = self.client.get(reverse('noticia', args=[sin_imagen.pk])).content.decode()
        self.assertIn('Esta noticia no tiene imagen disponible', html)
        self.assertNotIn('data-news-image-fallback', html)

    def test_ficha_rss_sin_imagen_no_intenta_renderizar_un_recurso(self):
        ficha = self.crear_publicacion(completa=False, titulo='Ficha RSS sin fotografía')
        html = self.client.get(reverse('noticia', args=[ficha.pk])).content.decode()
        self.assertIn('Ficha RSS enlazada.', html)
        self.assertNotIn('data-news-image-fallback', html)
        self.assertNotIn('<figure class="news-detail__media"', html)

    def test_buscador_reutiliza_el_fallback_y_conserva_imagen_original(self):
        self.crear_publicacion(imagen_url='https://imagenes.invalid/foto.jpg', titulo='Incendio controlado regional')
        html = self.client.get(reverse('buscar_noticias'), {'q': 'incendio'}).content.decode()
        self.assertIn('data-news-image-fallback', html)
        self.assertIn('data-news-image-placeholder hidden', html)
        self.assertIn('https://imagenes.invalid/foto.jpg', html)

    def test_buscador_muestra_fallback_si_no_hay_url_incluidas_fichas_rss(self):
        self.crear_publicacion(titulo='Incendio sin fotografía')
        html = self.client.get(reverse('buscar_noticias'), {'q': 'incendio'}).content.decode()
        self.assertIn('data-news-image-placeholder aria-hidden="true">Sin fotografía disponible', html)
        self.assertNotIn('data-news-image-fallback', html)

    def test_javascript_compartido_cubre_cargas_fallidas_y_no_reasigna_src(self):
        from pathlib import Path

        script = Path(__file__).resolve().parents[1] / 'static/js/news-image-fallback.js'
        contenido = script.read_text(encoding='utf-8')
        self.assertIn("document.addEventListener('error'", contenido)
        self.assertIn("imagen.hidden = true", contenido)
        self.assertIn("fallback.hidden = false", contenido)
        self.assertIn('imagen.complete && imagen.naturalWidth === 0', contenido)
        self.assertNotIn('imagen.src =', contenido)
