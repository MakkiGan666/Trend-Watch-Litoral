"""Regresiones UI con El Territorio y Noticias del 6, sin servicios externos."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Max
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Categoria, ClicPublicacion, Comentario, Etiqueta, Publicacion,
    PublicacionEtiqueta, Sentimiento, ValoracionPublicacion,
)
from core.services.clasificacion import vincular_categoria
from core.services.indicadores import resumen_publicaciones
from core.services.relevancia import (
    noticias_destacadas, noticias_destacadas_por_categoria, tendencias_destacadas,
)


class RegresionesUIMultifuenteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user(
            username='lector_h44b', password='synthetic-only',
        )
        cls.admin = get_user_model().objects.create_superuser(
            username='admin_h44b', password='synthetic-only',
        )
        cls.categoria = Categoria.objects.create(nombre_categoria='Salud')
        cls.etiqueta = Etiqueta.objects.create(nombre='Ensayo H4.4-B', slug='ensayo-h44b')
        cls.territorio = cls.crear_publicacion(
            'El Territorio (Misiones)', 'https://www.elterritorio.com.ar/h44b/territorio.png',
        )
        cls.noticias_del_6 = cls.crear_publicacion(
            'Noticias del 6', 'https://noticiasdel6.com/h44b/noticias-del-6.png',
        )

    @classmethod
    def crear_publicacion(cls, fuente, imagen):
        titulo = 'Misiones: proyecto comunitario sintético para mejorar la salud'
        publicacion = Publicacion.objects.create(
            hash_origen=f'h44b-{fuente.lower().replace(" ", "-")}',
            fuente=fuente,
            titulo=titulo,
            contenido=('Artículo de prueba sintético sobre salud comunitaria en Misiones. '
                       'No corresponde a una noticia ni contiene contenido editorial real.'),
            url=f'https://{("noticiasdel6.com" if fuente == "Noticias del 6" else "elterritorio.com.ar")}/h44b/original',
            imagen_url=imagen,
            fecha_publicacion=timezone.now(),
            departamento='capital',
        )
        vincular_categoria(publicacion, cls.categoria)
        posicion = (PublicacionEtiqueta.objects.filter(publicacion=publicacion)
                   .aggregate(maxima=Max('posicion'))['maxima'] or 0) + 1
        PublicacionEtiqueta.objects.create(
            publicacion=publicacion, etiqueta=cls.etiqueta, posicion=posicion,
        )
        return publicacion

    def test_listado_detalle_busqueda_autocompletado_imagenes_y_relaciones(self):
        respuesta = self.client.get(reverse('listar_publicaciones'))
        self.assertEqual(respuesta.status_code, 200)
        filas = respuesta.json()['data']
        por_fuente = {fila['fuente']: fila for fila in filas}
        self.assertIn('El Territorio (Misiones)', por_fuente)
        self.assertIn('Noticias del 6', por_fuente)
        self.assertEqual(por_fuente['El Territorio (Misiones)']['id'], self.territorio.pk)
        self.assertEqual(por_fuente['Noticias del 6']['id'], self.noticias_del_6.pk)
        for publicacion in (self.territorio, self.noticias_del_6):
            detalle_api = self.client.get(
                reverse('detalle_publicacion', args=[publicacion.pk]),
            ).json()
            self.assertEqual(detalle_api['fuente'], publicacion.fuente)
            self.assertEqual(detalle_api['url'], publicacion.url)

        consulta = self.client.get(reverse('buscar_publicaciones'), {'q': 'proyecto salud'}).json()
        self.assertEqual({fila['fuente'] for fila in consulta['resultados']},
                         {'El Territorio (Misiones)', 'Noticias del 6'})
        self.assertEqual({fila['imagen_url'] for fila in consulta['resultados']},
                         {self.territorio.imagen_url, self.noticias_del_6.imagen_url})
        busqueda_html = self.client.get(reverse('buscar_noticias'), {'q': 'proyecto salud'})
        self.assertEqual(busqueda_html.status_code, 200)
        self.assertContains(busqueda_html, 'El Territorio (Misiones)')
        self.assertContains(busqueda_html, 'Noticias del 6')
        self.assertContains(busqueda_html, self.territorio.imagen_url)
        self.assertContains(busqueda_html, self.noticias_del_6.imagen_url)
        sugerencias = self.client.get(reverse('sugerencias_publicaciones'), {'q': 'misiones'}).json()
        self.assertEqual({noticia['url'] for noticia in sugerencias['noticias']}, {
            reverse('noticia', args=[self.territorio.pk]),
            reverse('noticia', args=[self.noticias_del_6.pk]),
        })

        for publicacion, fuente, imagen in (
            (self.territorio, 'El Territorio (Misiones)', self.territorio.imagen_url),
            (self.noticias_del_6, 'Noticias del 6', self.noticias_del_6.imagen_url),
        ):
            with self.subTest(fuente=fuente):
                detalle = self.client.get(reverse('noticia', args=[publicacion.pk]))
                self.assertEqual(detalle.status_code, 200)
                self.assertContains(detalle, fuente)
                self.assertContains(detalle, imagen)
                self.assertContains(detalle, 'Salud')
                self.assertContains(detalle, reverse('publicaciones_etiqueta', args=['ensayo-h44b']))
                self.assertEqual(list(detalle.context['categorias_noticia']), ['Salud'])
                self.assertIn(
                    self.etiqueta.pk,
                    [rel.etiqueta_id for rel in detalle.context['etiquetas_noticia']],
                )

        categoria = self.client.get(reverse('publicaciones_categoria', args=['salud']))
        etiqueta = self.client.get(reverse('publicaciones_etiqueta', args=['ensayo-h44b']))
        for pagina in (categoria.context['pagina'], etiqueta.context['pagina']):
            self.assertEqual(pagina.paginator.count, 2)
            self.assertEqual({p.fuente for p in pagina},
                             {'El Territorio (Misiones)', 'Noticias del 6'})
        self.assertEqual(Publicacion.objects.count(), 2)

    def test_busqueda_pagina_dos_y_filtros_por_fuente(self):
        ahora = timezone.now()
        fuentes_lote = (
            ['El Territorio (Misiones)', 'Noticias del 6']
            + ['El Territorio (Misiones)'] * 11
            + ['Noticias del 6'] * 7
            + ['El Territorio (Misiones)', 'Noticias del 6']
        )
        for indice, fuente in enumerate(fuentes_lote):
            Publicacion.objects.create(
                hash_origen=f'h44b-pagina-{indice}', fuente=fuente,
                titulo=f'Obra vial sintética Misiones expediente H44B {indice}',
                contenido='Registro sintético para comprobar paginación multifuente.',
                fecha_publicacion=ahora + timedelta(seconds=indice),
            )

        pagina_uno = self.client.get(reverse('buscar_publicaciones'), {'q': 'obra vial', 'page': 1}).json()
        pagina_dos = self.client.get(reverse('buscar_publicaciones'), {'q': 'obra vial', 'page': 2}).json()
        self.assertEqual((pagina_uno['total'], pagina_uno['total_paginas']), (22, 2))
        self.assertEqual(len(pagina_uno['resultados']), 20)
        self.assertEqual(len(pagina_dos['resultados']), 2)
        fuentes = {'El Territorio (Misiones)', 'Noticias del 6'}
        self.assertEqual({p['fuente'] for p in pagina_uno['resultados']}, fuentes)
        self.assertEqual({p['fuente'] for p in pagina_dos['resultados']}, fuentes)

        self.client.force_login(self.admin)
        esperadas_por_fuente = {
            'El Territorio': ('El Territorio (Misiones)', 14),
            'Noticias del 6': ('Noticias del 6', 10),
        }
        for fuente, (nombre_almacenado, cantidad) in esperadas_por_fuente.items():
            respuesta = self.client.get(reverse('publicaciones'), {'fuente': fuente})
            self.assertEqual(respuesta.status_code, 200)
            self.assertEqual(respuesta.context['resumen']['total'], cantidad)
            self.assertEqual({p.fuente for p in respuesta.context['publicaciones']},
                             {nombre_almacenado})

        for fuente, publicacion in (('El Territorio (Misiones)', self.territorio),
                                    ('Noticias del 6', self.noticias_del_6)):
            Sentimiento.objects.create(id_publicacion_api=publicacion, polaridad=.4, confianza=.8)
        self.assertEqual(resumen_publicaciones(Publicacion.objects.all()), {
            'total': 24, 'analizadas': 2, 'pendientes': 22, 'inconsistentes': 0,
        })
        self.assertEqual(self.territorio.fuente, 'El Territorio (Misiones)')
        for fuente, (nombre_almacenado, cantidad) in {
            'El Territorio': ('El Territorio', 14),
            'Noticias del 6': ('Noticias del 6', 10),
        }.items():
            dashboard = self.client.get(reverse('dashboard'), {'fuente': fuente})
            self.assertEqual(dashboard.status_code, 200)
            self.assertEqual(dashboard.context['resumen']['total'], cantidad)
            self.assertEqual(dashboard.context['resumen']['analizadas'], 1)
            self.assertEqual(dashboard.context['filtros']['fuente'].value(), fuente)
            fuentes_dashboard = {
                fila['nombre']: fila['total'] for fila in dashboard.context['fuentes']
            }
            self.assertEqual(fuentes_dashboard, {nombre_almacenado: cantidad})
            if fuente == 'El Territorio':
                self.assertEqual(self.territorio.fuente, 'El Territorio (Misiones)')

    def test_similares_de_medios_distintos_siguen_independientes_en_destacadas_y_tendencias(self):
        segundo_usuario = get_user_model().objects.create_user(
            username='lector_h44b_secundario', password='synthetic-only',
        )
        for publicacion in (self.territorio, self.noticias_del_6):
            ClicPublicacion.objects.create(usuario=self.usuario, publicacion=publicacion)
            for usuario in (self.usuario, segundo_usuario):
                ValoracionPublicacion.objects.create(
                    usuario=usuario, publicacion=publicacion, sentimiento='positivo',
                )
        self.assertEqual(set(noticias_destacadas()), {self.territorio, self.noticias_del_6})
        por_categoria = next(
            grupo for grupo in noticias_destacadas_por_categoria()
            if grupo['nombre'] == 'Salud'
        )
        self.assertEqual({p.pk for p in por_categoria['publicaciones']},
                         {self.territorio.pk, self.noticias_del_6.pk})
        tendencias = tendencias_destacadas()
        self.assertEqual({item['publicacion'].pk for item in tendencias},
                         {self.territorio.pk, self.noticias_del_6.pk})

    def test_comentarios_y_valoraciones_permanecen_vinculados_a_su_publicacion(self):
        self.client.force_login(self.usuario)
        publicaciones = (self.territorio, self.noticias_del_6)
        textos = ('Comentario sintético Territorio', 'Comentario sintético Noticias del 6')
        sentimientos = ('positivo', 'negativo')
        for publicacion, texto, sentimiento in zip(publicaciones, textos, sentimientos):
            comentario = self.client.post(
                reverse('crear_comentario', args=[publicacion.pk]), {'texto': texto},
            )
            valoracion = self.client.post(
                reverse('valorar_noticia', args=[publicacion.pk]), {'sentimiento': sentimiento},
            )
            self.assertEqual(comentario.status_code, 302)
            self.assertEqual(valoracion.status_code, 302)

        self.assertEqual(list(Comentario.objects.order_by('publicacion_id').values_list(
            'publicacion_id', 'texto')),
            [(self.territorio.pk, textos[0]), (self.noticias_del_6.pk, textos[1])])
        self.assertEqual(list(ValoracionPublicacion.objects.order_by('publicacion_id').values_list(
            'publicacion_id', 'sentimiento')),
            [(self.territorio.pk, 'positivo'), (self.noticias_del_6.pk, 'negativo')])
        for publicacion, visible, oculto, sentimiento in (
            (self.territorio, textos[0], textos[1], 'positivo'),
            (self.noticias_del_6, textos[1], textos[0], 'negativo'),
        ):
            detalle = self.client.get(reverse('noticia', args=[publicacion.pk]))
            self.assertContains(detalle, visible)
            self.assertNotContains(detalle, oculto)
            self.assertEqual(detalle.context['valoracion_propia'], sentimiento)
            self.assertEqual(detalle.context['valoraciones_total'], 1)

    def test_ranking_valorado_mantiene_publicaciones_de_ambas_fuentes(self):
        for indice in range(3):
            lector = get_user_model().objects.create_user(
                username=f'lector_h44d_ranking_{indice}', password='synthetic-only',
            )
            for publicacion in (self.territorio, self.noticias_del_6):
                ValoracionPublicacion.objects.create(
                    usuario=lector, publicacion=publicacion, sentimiento='positivo',
                )
        pagina = self.client.get(reverse('categorias'))
        self.assertEqual(pagina.status_code, 200)
        self.assertEqual(
            {p.pk for p in pagina.context['ranking_positivo']},
            {self.territorio.pk, self.noticias_del_6.pk},
        )
