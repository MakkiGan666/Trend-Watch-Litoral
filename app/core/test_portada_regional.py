from unittest.mock import patch
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Categoria, ClicPublicacion, Comentario, Publicacion, PublicacionGuardada,
    Tema, TemaTrend,
)
from core.services.clasificacion import CATEGORIAS_PROYECTO, vincular_categoria


class CategoriasYPortadaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.lector = get_user_model().objects.create_user('lector_regional', password='prueba-no-real')
        cls.local = Publicacion.objects.create(
            hash_origen='regional-local', titulo='Nueva escuela en Posadas', contenido='Noticia local', departamento='capital',
        )
        cls.nacional = Publicacion.objects.create(
            hash_origen='regional-nacional', titulo='Mercado nacional', contenido='Noticia nacional',
        )
        cls.categoria = Categoria.objects.create(nombre_categoria='Educación')
        vincular_categoria(cls.local, cls.categoria)

    def test_muestra_las_doce_categorias_y_listado_completo_paginado(self):
        portada = self.client.get(reverse('categorias'))
        for nombre in CATEGORIAS_PROYECTO:
            self.assertContains(portada, f'<h3>{nombre}</h3>', html=False)
        self.assertNotContains(portada, 'id="grafico"')
        url = reverse('publicaciones_categoria', args=['educacion'])
        for i in range(25):
            noticia = Publicacion.objects.create(hash_origen=f'educacion-{i}', titulo=f'Escuela {i}', contenido='Texto')
            vincular_categoria(noticia, self.categoria)
        primera = self.client.get(url)
        self.assertEqual(primera.context['pagina'].paginator.count, 26)
        self.assertEqual(len(primera.context['pagina']), 24)
        self.assertEqual(len(self.client.get(url + '?pagina=2').context['pagina']), 2)
        self.assertNotContains(primera, 'Mercado nacional')

    def test_inicio_muestra_solo_noticias_regionales(self):
        pagina = self.client.get(reverse('landing'))
        self.assertContains(pagina, 'Nueva escuela en Posadas')
        self.assertNotContains(pagina, 'Mercado nacional')
        grupos = pagina.context['categorias_inicio']
        self.assertEqual([grupo['nombre'] for grupo in grupos], CATEGORIAS_PROYECTO)
        educacion = next(grupo for grupo in grupos if grupo['nombre'] == 'Educación')
        self.assertEqual([noticia.pk for noticia in educacion['publicaciones']], [self.local.pk])
        self.assertTrue(all(len(grupo['publicaciones']) <= 15 for grupo in grupos))
        self.assertContains(pagina, 'Selección regional')

    def test_inicio_limita_a_quince_por_categoria_y_elimina_duplicados(self):
        for i in range(20):
            noticia = Publicacion.objects.create(hash_origen=f'regional-extra-{i}', titulo=f'Noticia {i} en Posadas',
                                                 contenido='Texto', departamento='capital')
            vincular_categoria(noticia, self.categoria)
        duplicada = Publicacion.objects.create(hash_origen='regional-duplicada', titulo='Noticia 0 en Posadas',
                                               contenido='Texto', departamento='capital')
        vincular_categoria(duplicada, self.categoria)
        salud = Categoria.objects.create(nombre_categoria='Salud')
        for i in range(17):
            noticia = Publicacion.objects.create(hash_origen=f'salud-regional-{i}', titulo=f'Hospital de Posadas {i}',
                                                 contenido='Texto', departamento='capital')
            vincular_categoria(noticia, salud)
        grupos = {grupo['nombre']: grupo['publicaciones'] for grupo in self.client.get(reverse('landing')).context['categorias_inicio']}
        self.assertEqual(len(grupos['Educación']), 15)
        self.assertEqual(len({noticia.titulo for noticia in grupos['Educación']}), 15)
        self.assertEqual(len(grupos['Salud']), 15)
        self.assertTrue(all(noticia.titulo.startswith('Hospital') for noticia in grupos['Salud']))
        self.assertEqual(grupos['Policiales'], [])

    def test_clic_unico_por_usuario_y_relacion_con_tendencia(self):
        self.local.imagen_url = 'https://cdn.ejemplo.com/portada-regional.webp'
        self.local.save(update_fields=['imagen_url'])
        url = reverse('noticia', args=[self.local.pk])
        self.client.get(url)
        self.assertFalse(ClicPublicacion.objects.exists())
        self.client.force_login(self.lector)
        self.client.get(url)
        self.client.get(url)
        self.assertEqual(ClicPublicacion.objects.filter(publicacion=self.local).count(), 1)
        tema = Tema.objects.get(id_categoria=self.categoria)
        self.assertTrue(TemaTrend.objects.filter(id_temas=tema, id_trends__relevancia='Lecturas').exists())
        portada = self.client.get(reverse('landing'))
        self.assertEqual(portada.context['tendencias_inicio'][0]['clics'], 1)
        self.assertContains(portada, 'https://cdn.ejemplo.com/portada-regional.webp')
        self.assertContains(portada, 'trend-card--lead')
        self.assertContains(self.client.get(reverse('categorias')), 'trend-card__media')

    def test_una_nueva_lectura_reactiva_una_noticia_antigua(self):
        self.client.force_login(self.lector)
        url = reverse('noticia', args=[self.local.pk])
        self.client.get(url)
        ClicPublicacion.objects.filter(publicacion=self.local).update(
            ultima_visita=timezone.now() - timedelta(days=8),
        )
        self.client.get(url)
        clic = ClicPublicacion.objects.get(publicacion=self.local)
        self.assertGreater(clic.ultima_visita, timezone.now() - timedelta(days=1))
        self.assertEqual(ClicPublicacion.objects.filter(publicacion=self.local).count(), 1)

    def test_guardados_recomienda_noticias_afines_sin_repetir_guardadas(self):
        PublicacionGuardada.objects.create(usuario=self.lector, publicacion=self.local)
        similar = Publicacion.objects.create(hash_origen='regional-similar', titulo='Otra escuela en Posadas',
                                              contenido='Texto', departamento='capital')
        vincular_categoria(similar, self.categoria)
        for i in range(4):
            otra = Publicacion.objects.create(hash_origen=f'regional-recomendacion-{i}',
                                               titulo=f'Otra noticia escolar {i}', contenido='Texto')
            vincular_categoria(otra, self.categoria)
        self.client.force_login(self.lector)
        pagina = self.client.get(reverse('mis_guardados'))
        self.assertEqual(len(pagina.context['recomendaciones']), 3)
        self.assertNotIn(self.local, pagina.context['recomendaciones'])


class ModeracionYAgendaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.lector = get_user_model().objects.create_user('comentador_regional', password='prueba-no-real')
        cls.noticia = Publicacion.objects.create(hash_origen='comentario-regional', titulo='Noticia', contenido='Texto')

    def test_comentarios_nuevos_esperan_revision_y_lenguaje_ofensivo_se_rechaza(self):
        self.client.force_login(self.lector)
        url = reverse('crear_comentario', args=[self.noticia.pk])
        self.assertEqual(self.client.post(url, {'texto': 'Qué buena noticia'}).status_code, 302)
        comentario = Comentario.objects.get()
        self.assertEqual(comentario.estado, Comentario.Estado.PENDIENTE)
        self.assertContains(self.client.get(reverse('noticia', args=[self.noticia.pk])), 'Pendiente de revisión')
        self.client.logout()
        self.assertNotContains(self.client.get(reverse('noticia', args=[self.noticia.pk])), 'Qué buena noticia')
        self.client.force_login(self.lector)
        rechazada = self.client.post(url, {'texto': 'Esto es una mierda'})
        self.assertEqual(rechazada.status_code, 400)
        self.assertContains(rechazada, 'Revisá tu comentario', status_code=400)
        self.assertNotContains(rechazada, 'Publicar comentario', status_code=400)
        self.assertEqual(self.client.post(url, {'texto': 'Esto es una m1erda'}).status_code, 400)
        self.assertEqual(Comentario.objects.count(), 1)
        comentario.estado = Comentario.Estado.PUBLICADO
        comentario.save(update_fields=['estado'])
        self.assertContains(self.client.get(reverse('noticia', args=[self.noticia.pk])), 'Qué buena noticia')

    @patch('core.management.commands.ingestar_recientes.fetch_and_store_elterritorio')
    def test_una_revision_consulta_todos_los_rss_sin_ia(self, ingestar):
        from core.services.scraper import CATEGORIAS_TERRITORIO

        ingestar.return_value = {'status': 'EXITO', 'capturados': 0}
        call_command('ingestar_recientes', '--una-vez', verbosity=0)
        self.assertEqual(ingestar.call_count, len(CATEGORIAS_TERRITORIO))
        self.assertTrue(all(call.kwargs['usar_ia'] is False for call in ingestar.call_args_list))
