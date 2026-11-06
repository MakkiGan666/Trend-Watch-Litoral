from unittest.mock import patch
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Categoria, ClicPublicacion, Comentario, Etiqueta, Publicacion, PublicacionEtiqueta, PublicacionGuardada,
    Tema, TemaTrend, ValoracionPublicacion,
)
from core.services.clasificacion import CATEGORIAS_PROYECTO, vincular_categoria
from core.services.relevancia import ejemplos_rankings, tendencias_destacadas


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

    def test_inicio_muestra_etiquetas_en_noticias_y_tendencias(self):
        etiqueta = self.local.etiquetas.select_related('etiqueta').first().etiqueta
        segundo = get_user_model().objects.create_user('lector_etiquetas')
        ValoracionPublicacion.objects.create(publicacion=self.local, usuario=self.lector, sentimiento='positivo')
        ValoracionPublicacion.objects.create(publicacion=self.local, usuario=segundo, sentimiento='neutral')
        pagina = self.client.get(reverse('landing'))
        url = reverse('publicaciones_etiqueta', args=[etiqueta.slug])
        self.assertContains(pagina, url, count=2)
        self.assertContains(pagina, 'Etiquetas de Nueva escuela en Posadas', count=2)
        html = pagina.content.decode()
        tarjeta_tendencia = html.split('class="trend-card__body"', 1)[1].split('</div>', 1)[0]
        self.assertLess(tarjeta_tendencia.index('trend-card__title'), tarjeta_tendencia.index('news-keywords--trend'))

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

    def test_clic_unico_por_usuario_sin_crear_tendencia(self):
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
        self.assertFalse(TemaTrend.objects.filter(id_temas=tema, id_trends__relevancia='Lecturas').exists())
        portada = self.client.get(reverse('landing'))
        self.assertEqual(portada.context['tendencias_inicio'], [])
        self.assertContains(portada, 'https://cdn.ejemplo.com/portada-regional.webp')
        self.assertContains(portada, 'Todavía no hay suficiente actividad reciente')

    def test_cobertura_reciente_agrupa_noticias_del_mismo_tema_sin_inventar_reacciones(self):
        etiqueta, _ = Etiqueta.objects.get_or_create(slug='crecida', defaults={'nombre': 'crecida'})
        noticias = [
            Publicacion.objects.create(hash_origen='crecida-balsa', titulo='Crecida del río interrumpe la balsa',
                                       contenido='El caudal subió.', departamento='capital'),
            Publicacion.objects.create(hash_origen='crecida-cruce', titulo='Cerraron el cruce por la crecida del río',
                                       contenido='El paso quedó cerrado.', departamento='capital'),
        ]
        for noticia in noticias:
            if not noticia.etiquetas.filter(etiqueta=etiqueta).exists():
                PublicacionEtiqueta.objects.create(publicacion=noticia, etiqueta=etiqueta,
                                                   posicion=noticia.etiquetas.count() + 1)
        tendencias = tendencias_destacadas()
        self.assertEqual({item['publicacion'].pk for item in tendencias}, {noticia.pk for noticia in noticias})
        self.assertTrue(all(item['cobertura'] and item['publicaciones_24h'] == 2 for item in tendencias))
        self.assertContains(self.client.get(reverse('categorias')), 'crecida · 2 noticias en 24 h')

    def test_tendencias_priorizan_velocidad_sobre_total_acumulado(self):
        acumulada = Publicacion.objects.create(hash_origen='tendencia-acumulada', titulo='Debate acumulado', contenido='Texto')
        acelerada = Publicacion.objects.create(hash_origen='tendencia-acelerada', titulo='Debate acelerado', contenido='Texto')
        votos_antiguos = []
        for indice in range(6):
            usuario = get_user_model().objects.create_user(f'lector_velocidad_{indice}')
            voto = ValoracionPublicacion.objects.create(publicacion=acumulada, usuario=usuario, sentimiento='neutral')
            if indice < 4:
                votos_antiguos.append(voto.pk)
            if indice < 2:
                ValoracionPublicacion.objects.create(publicacion=acelerada, usuario=usuario, sentimiento='positivo')
        ValoracionPublicacion.objects.filter(pk__in=votos_antiguos).update(
            fecha_actualizacion=timezone.now() - timedelta(days=2),
        )
        tendencias = tendencias_destacadas()
        self.assertEqual([item['publicacion'].pk for item in tendencias[:2]], [acelerada.pk, acumulada.pk])

    def test_tendencias_muestran_hasta_diez_noticias_en_ambas_vistas(self):
        lectores = [get_user_model().objects.create_user(f'lector_tendencias_10_{indice}') for indice in range(2)]
        for indice in range(12):
            noticia = Publicacion.objects.create(
                hash_origen=f'tendencia-10-{indice}', titulo=f'Debate regional número {indice} en Misiones', contenido='Texto',
            )
            for lector in lectores:
                ValoracionPublicacion.objects.create(publicacion=noticia, usuario=lector, sentimiento='neutral')
        for nombre, contexto in (('landing', 'tendencias_inicio'), ('categorias', 'tendencias')):
            pagina = self.client.get(reverse(nombre))
            ids = [item['publicacion'].pk for item in pagina.context[contexto]]
            self.assertEqual(len(ids), 10)
            self.assertEqual(len(set(ids)), 10)
            self.assertContains(pagina, 'Hasta diez noticias de Tendencias; desplazá para ver más')

    def test_tendencias_cuentan_valoraciones_y_comentaristas_publicados_sin_clics(self):
        otra = Publicacion.objects.create(hash_origen='regional-interacciones', titulo='Debate regional en Misiones',
                                          contenido='Texto', departamento='capital')
        segundo = get_user_model().objects.create_user('lector_dos')
        ValoracionPublicacion.objects.create(publicacion=otra, usuario=self.lector, sentimiento='negativo')
        Comentario.objects.create(publicacion=otra, autor=segundo, texto='Opinión publicada', estado='publicado')
        Comentario.objects.create(publicacion=otra, autor=segundo, texto='Otra opinión', estado='publicado')
        Comentario.objects.create(publicacion=otra, autor=self.lector, texto='Sin publicar', estado='pendiente')
        ClicPublicacion.objects.create(publicacion=self.local, usuario=segundo)
        inicio = self.client.get(reverse('landing'))
        categorias = self.client.get(reverse('categorias'))
        for respuesta, clave in ((inicio, 'tendencias_inicio'), (categorias, 'tendencias')):
            self.assertEqual(respuesta.context[clave][0]['publicacion'], otra)
            self.assertEqual(respuesta.context[clave][0]['participaciones'], 2)
            self.assertContains(respuesta, '2 participaciones')

    def test_rankings_exigen_respuestas_reales_y_opiniones_divididas(self):
        positiva = Publicacion.objects.create(hash_origen='ranking-positivo', titulo='Noticia valorada positivamente', contenido='Texto')
        polemica = Publicacion.objects.create(hash_origen='ranking-polemico', titulo='Noticia con opiniones divididas', contenido='Texto')
        for indice in range(5):
            usuario = get_user_model().objects.create_user(f'votante_{indice}')
            ValoracionPublicacion.objects.create(publicacion=positiva, usuario=usuario, sentimiento='positivo')
            ValoracionPublicacion.objects.create(publicacion=polemica, usuario=usuario,
                                                sentimiento='positivo' if indice < 2 else 'negativo')
        pagina = self.client.get(reverse('categorias'))
        self.assertEqual([p.pk for p in pagina.context['ranking_positivo']], [positiva.pk])
        self.assertEqual([p.pk for p in pagina.context['ranking_polemico']], [polemica.pk])
        self.assertContains(pagina, 'Lo más polémico')
        self.assertContains(pagina, 'ranking-card__keywords', count=2)
        for publicacion in (positiva, polemica):
            etiqueta = publicacion.etiquetas.select_related('etiqueta').first().etiqueta
            self.assertContains(pagina, reverse('publicaciones_etiqueta', args=[etiqueta.slug]))

    def test_vistas_previas_eligen_noticias_por_contenido_y_no_solo_categoria(self):
        logro = Publicacion.objects.create(
            hash_origen='previa-logro', titulo='Voluntarios rescataron una especie y lograron recuperarla',
            contenido='La comunidad celebró el rescate y colaboró con los voluntarios.',
        )
        debate = Publicacion.objects.create(
            hash_origen='previa-debate', titulo='Vecinos rechazan una reforma y denuncian un conflicto',
            contenido='La propuesta provocó críticas y abrió un debate entre dos sectores.',
        )
        Publicacion.objects.create(
            hash_origen='previa-temporal', titulo='Temporal dejó dos familias evacuadas',
            contenido='La tormenta afectó varias casas.',
        )
        Publicacion.objects.create(
            hash_origen='previa-politica', titulo='La oposición logró un avance contra el gobierno',
            contenido='El debate entre los partidos provocó críticas.',
        )
        Publicacion.objects.create(
            hash_origen='previa-deportes', titulo='El equipo dio el golpe y logró su triunfo',
            contenido='Ganó un partido de fútbol.',
        )
        positivas, polemicas = ejemplos_rankings()
        self.assertEqual([p.pk for p in positivas], [logro.pk])
        self.assertEqual([p.pk for p in polemicas], [debate.pk])

    def test_cada_ranking_muestra_hasta_quince_noticias_sin_repetir_las_votadas(self):
        for indice in range(16):
            Publicacion.objects.create(
                hash_origen=f'positiva-15-{indice}',
                titulo=f'Voluntarios rescataron a una familia en el barrio {indice}',
                contenido='La comunidad colaboró con los voluntarios.',
            )
            Publicacion.objects.create(
                hash_origen=f'polemica-15-{indice}',
                titulo=f'Vecinos rechazan una reforma en el barrio {indice}',
                contenido='La medida despertó críticas y abrió un debate.',
            )
        votada = Publicacion.objects.get(hash_origen='positiva-15-0')
        for indice in range(3):
            usuario = get_user_model().objects.create_user(f'lector_ranking_15_{indice}')
            ValoracionPublicacion.objects.create(publicacion=votada, usuario=usuario, sentimiento='positivo')
        pagina = self.client.get(reverse('categorias'))
        self.assertEqual(len(pagina.context['ranking_positivo']), 1)
        self.assertEqual(len(pagina.context['ejemplos_positivos']), 14)
        self.assertEqual(len(pagina.context['ejemplos_polemicos']), 15)
        self.assertNotIn(votada.pk, [p.pk for p in pagina.context['ejemplos_positivos']])
        self.assertContains(pagina, 'class="ranking-card"', count=30)
        self.assertContains(pagina, 'class="ranking-list" tabindex="0"', count=2)

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
