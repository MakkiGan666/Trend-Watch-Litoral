from datetime import datetime, timezone

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Publicacion, Sentimiento, ValoracionPublicacion
from core.services.indicadores import resumen_publicaciones
from core.services.relevancia import ejemplos_rankings, rankings_valoraciones


class FichasRSSVisualizacionTests(TestCase):
    def crear_ficha(self, **datos):
        valores = {
            'hash_origen': 'ficha-rss',
            'fuente': 'Diario Litoral',
            'titulo': 'Aviso auténtico del feed sobre transporte',
            'contenido': '',
            'contenido_completo': False,
            'url': 'https://diario.example/noticia/transporte',
            'fecha_publicacion': datetime(2026, 11, 8, 10, tzinfo=timezone.utc),
        }
        valores.update(datos)
        return Publicacion.objects.create(**valores)

    def crear_articulo(self, **datos):
        valores = {
            'hash_origen': 'articulo-completo',
            'fuente': 'El Territorio',
            'titulo': 'Rescatan a una familia tras una crecida en Misiones',
            'contenido': 'El artículo completo describe el operativo y sus resultados.',
            'contenido_completo': True,
            'url': 'https://territorio.example/noticia/rescate',
            'imagen_url': 'https://territorio.example/foto.jpg',
            'fecha_publicacion': datetime(2026, 11, 7, 10, tzinfo=timezone.utc),
        }
        valores.update(datos)
        return Publicacion.objects.create(**valores)

    def test_portada_identifica_ficha_sin_imagen_ni_extracto(self):
        ficha = self.crear_ficha(fecha_publicacion=None, imagen_url='')
        response = self.client.get(reverse('landing'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Fichas enlazadas')
        self.assertContains(response, ficha.titulo)
        self.assertContains(response, ficha.fuente)
        self.assertContains(response, reverse('noticia', args=[ficha.pk]))
        self.assertNotContains(response, 'Imagen no disponible')

    def test_busqueda_por_titulo_y_fuente_no_consulta_cuerpo_de_ficha(self):
        ficha = self.crear_ficha()
        articulo = self.crear_articulo()

        por_titulo = self.client.get(reverse('buscar_noticias'), {'q': 'transporte'})
        self.assertEqual(por_titulo.status_code, 200)
        resultado = next(r for r in por_titulo.context['resultados'] if r['fuente'] == ficha.fuente)
        self.assertIsNone(resultado['extracto'])
        self.assertTrue(resultado['es_ficha_rss'])
        self.assertContains(por_titulo, 'Ficha RSS · sin cuerpo completo')

        por_fuente = self.client.get(reverse('buscar_noticias'), {'q': 'Diario Litoral'})
        self.assertEqual(por_fuente.status_code, 200)
        self.assertEqual([r['fuente'] for r in por_fuente.context['resultados']], [ficha.fuente])
        api = self.client.get(reverse('buscar_publicaciones'), {'q': 'Diario Litoral'}).json()
        self.assertEqual([r['id_publicacion_api'] for r in api['resultados']], [ficha.pk])
        self.assertIsNone(api['resultados'][0]['extracto'])
        self.assertNotIn(articulo.pk, [r['id_publicacion_api'] for r in api['resultados']])

    def test_detalle_ficha_muestra_titulo_fuente_fecha_y_enlace_original(self):
        ficha = self.crear_ficha(fecha_publicacion=None, imagen_url='')
        response = self.client.get(reverse('noticia', args=[ficha.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, ficha.titulo)
        self.assertContains(response, ficha.fuente)
        self.assertContains(response, 'Ficha RSS enlazada')
        self.assertEqual(response.context['fecha_navegacion']['fecha_origen'], 'captura')
        self.assertContains(response, 'Incorporada el')
        self.assertContains(response, 'href="https://diario.example/noticia/transporte"')
        self.assertContains(response, 'el artículo completo no está almacenado')
        self.assertNotContains(response, 'news-detail__placeholder')
        self.assertNotContains(response, 'Sin categoría asociada')
        self.assertNotContains(response, 'Localidad sin identificar')
        self.assertNotContains(response, 'El contenido de esta noticia todavía no está disponible')

    def test_articulo_completo_conserva_cuerpo_e_imagen(self):
        articulo = self.crear_articulo()
        response = self.client.get(reverse('noticia', args=[articulo.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, articulo.contenido)
        self.assertContains(response, 'src="https://territorio.example/foto.jpg"')
        self.assertNotContains(response, 'Ficha RSS enlazada')

    def test_indicadores_separan_total_fichas_y_analisis(self):
        articulo = self.crear_articulo()
        ficha = self.crear_ficha()
        # Simula una fila de sentimiento inconsistente: tampoco debe contar
        # como análisis de una ficha RSS.
        Sentimiento.objects.create(id_publicacion_api=articulo, polaridad=.7, confianza=.9)
        # Simula una fila inconsistente histórica que evadió la validación del
        # modelo; los indicadores deben seguir excluyéndola por el tipo de post.
        Sentimiento.objects.bulk_create([
            Sentimiento(id_publicacion_api=ficha, polaridad=.8, confianza=.9),
        ])
        resumen = resumen_publicaciones(Publicacion.objects.all())
        self.assertEqual(resumen, {
            'total': 2, 'articulos_completos': 1, 'fichas_rss': 1,
            'sin_cuerpo_sin_ficha': 0, 'analizadas': 1,
            'pendientes': 0, 'inconsistentes': 0,
        })

        root = get_user_model().objects.create_superuser('rss_dash_root', 'rss@example.invalid', None)
        self.client.force_login(root)
        dashboard = self.client.get(reverse('dashboard'))
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.context['resumen'], resumen)
        self.assertEqual(sum(f['total'] for f in dashboard.context['fuentes']), 2)
        self.assertEqual(sum(f['total'] for f in dashboard.context['sentimientos']), 1)
        self.assertContains(dashboard, 'Fichas RSS')

    def test_rankings_por_contenido_excluyen_fichas_aunque_el_titulo_tenga_senales(self):
        articulo = self.crear_articulo()
        ficha = self.crear_ficha(
            titulo='Rescatan y ayudan a familias de Misiones tras la crecida',
            hash_origen='ficha-senal-ranking',
        )
        positivos, polemicos = ejemplos_rankings()
        self.assertIn(articulo, positivos)
        self.assertNotIn(ficha, positivos)
        self.assertNotIn(ficha, polemicos)

    def test_rankings_por_participacion_admiten_ficha_y_la_identifican(self):
        ficha = self.crear_ficha()
        usuarios = [
            get_user_model().objects.create_user(f'rss_lector_{indice}')
            for indice in range(3)
        ]
        ValoracionPublicacion.objects.bulk_create([
            ValoracionPublicacion(
                publicacion=ficha, usuario=usuario,
                sentimiento=ValoracionPublicacion.Sentimiento.POSITIVO,
            )
            for usuario in usuarios
        ])

        positivas, _ = rankings_valoraciones()
        self.assertIn(ficha, positivas)
        portada = self.client.get(reverse('landing'))
        self.assertContains(portada, 'Ficha RSS · sin cuerpo completo')
        self.assertNotContains(portada, 'trend-card__media')
