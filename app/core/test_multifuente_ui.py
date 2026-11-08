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
    def crear_publicacion(cls, fuente, imagen, *, marcador=None):
        hosts = {
            'El Territorio (Misiones)': 'elterritorio.com.ar',
            'Noticias del 6': 'noticiasdel6.com',
            'Eldorado Noticias': 'eldoradonoticias.com.ar',
            'Norte Misionero': 'nortemisionero.com.ar',
            'Fracrán Noticias': 'fracran.com.ar',
        }
        host = hosts[fuente]
        sufijo = f' H45B {marcador}' if marcador else ''
        titulo = f'Misiones: proyecto comunitario sintético para mejorar la salud{sufijo}'
        publicacion = Publicacion.objects.create(
            hash_origen=f'h44b-{fuente.lower().replace(" ", "-")}-{marcador or "base"}',
            fuente=fuente,
            titulo=titulo,
            contenido=(f'Artículo sintético H45B {marcador or "base"} sobre salud comunitaria en Misiones. '
                       'No corresponde a una noticia ni contiene contenido editorial real.'),
            url=f'https://{host}/h44b/{marcador or "original"}',
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

    def test_cinco_fuentes_en_listados_busqueda_filtros_analitica_y_detalles(self):
        hosts = {
            'El Territorio (Misiones)': 'elterritorio.com.ar',
            'Noticias del 6': 'noticiasdel6.com',
            'Eldorado Noticias': 'eldoradonoticias.com.ar',
            'Norte Misionero': 'nortemisionero.com.ar',
            'Fracrán Noticias': 'fracran.com.ar',
        }
        fuentes = (
            ('El Territorio (Misiones)', 'territorio45'),
            ('Noticias del 6', 'del6'),
            ('Eldorado Noticias', 'eldorado45'),
            ('Norte Misionero', 'norte45'),
            ('Fracrán Noticias', 'fracran45'),
        )
        # Reescribir las dos filas iniciales del fixture para que cada resultado
        # tenga una identidad rastreable; la BD de TestCase es aislada.
        publicaciones_por_fuente = {
            'El Territorio (Misiones)': self.territorio,
            'Noticias del 6': self.noticias_del_6,
        }
        ahora = timezone.now()
        for indice, (fuente, marcador) in enumerate(fuentes[:2]):
            publicacion = publicaciones_por_fuente[fuente]
            publicacion.titulo = (
                f'Misiones: proyecto comunitario sintético H45B {marcador} para mejorar la salud'
            )
            publicacion.contenido = (
                f'Artículo sintético H45B {marcador} sobre salud comunitaria en Misiones. '
                'No corresponde a una noticia ni contiene contenido editorial real.'
            )
            publicacion.url = f'https://{hosts[fuente]}/h45b/{marcador}/original'
            publicacion.imagen_url = f'https://{hosts[fuente]}/h45b/{marcador}/imagen.png'
            publicacion.fecha_publicacion = ahora + timedelta(seconds=indice)
            publicacion.departamento = 'capital'
            publicacion.save(update_fields=(
                'titulo', 'contenido', 'url', 'imagen_url', 'fecha_publicacion', 'departamento',
            ))

        for fuente, marcador in fuentes[2:]:
            imagen = f'https://{hosts[fuente]}/h45b/{marcador}/imagen.png'
            publicaciones_por_fuente[fuente] = self.crear_publicacion(
                fuente, imagen, marcador=marcador,
            )
            publicaciones_por_fuente[fuente].fecha_publicacion = ahora + timedelta(seconds=2)
            publicaciones_por_fuente[fuente].departamento = 'capital'
            publicaciones_por_fuente[fuente].save(update_fields=('fecha_publicacion', 'departamento'))

        categorias_por_fuente = {}
        etiquetas_por_fuente = {}
        for fuente, marcador in fuentes:
            publicacion = publicaciones_por_fuente[fuente]
            categoria = Categoria.objects.create(nombre_categoria=f'Ensayo {marcador}')
            etiqueta = Etiqueta.objects.create(
                nombre=f'Etiqueta {marcador}', slug=f'h45b-{marcador}',
            )
            vincular_categoria(publicacion, categoria)
            posicion = (PublicacionEtiqueta.objects.filter(publicacion=publicacion)
                       .aggregate(maxima=Max('posicion'))['maxima'] or 0) + 1
            PublicacionEtiqueta.objects.create(
                publicacion=publicacion, etiqueta=etiqueta, posicion=posicion,
            )
            categorias_por_fuente[fuente] = categoria
            etiquetas_por_fuente[fuente] = etiqueta
            Sentimiento.objects.create(
                id_publicacion_api=publicacion,
                polaridad=(len(publicaciones_por_fuente) - len(categorias_por_fuente)) / 4 - .5,
                confianza=.8,
            )
            ClicPublicacion.objects.create(usuario=self.usuario, publicacion=publicacion)
            Comentario.objects.create(
                publicacion=publicacion, autor=self.usuario,
                texto=f'Comentario público sintético H45B {marcador}.',
                estado=Comentario.Estado.PUBLICADO,
            )

        lectores = [self.admin, self.usuario]
        lectores.extend(get_user_model().objects.create_user(
            username=f'lector_h45b_{indice}', password='synthetic-only',
        ) for indice in range(1, 6))
        votos_por_marcador = {
            'territorio45': ('positivo', 'positivo', 'positivo', 'negativo', 'negativo'),
            'del6': ('negativo', 'positivo', 'positivo', 'positivo', 'negativo', 'negativo', 'neutral'),
            'eldorado45': ('neutral', 'positivo', 'positivo', 'positivo', 'negativo', 'negativo', 'neutral'),
            'norte45': ('positivo', 'positivo', 'positivo', 'positivo', 'negativo', 'negativo', 'neutral'),
            'fracran45': ('negativo', 'positivo', 'positivo', 'positivo', 'positivo', 'negativo', 'negativo'),
        }
        for fuente, marcador in fuentes:
            publicacion = publicaciones_por_fuente[fuente]
            for lector, sentimiento in zip(lectores, votos_por_marcador[marcador]):
                ValoracionPublicacion.objects.create(
                    usuario=lector, publicacion=publicacion,
                    sentimiento=sentimiento,
                )

        ids_esperados = {publicacion.pk for publicacion in publicaciones_por_fuente.values()}
        por_marcador = {
            marcador: publicaciones_por_fuente[fuente]
            for fuente, marcador in fuentes
        }

        listado_html = self.client.get(reverse('landing'))
        self.assertEqual(listado_html.status_code, 200)
        for fuente, marcador in fuentes:
            publicacion = publicaciones_por_fuente[fuente]
            with self.subTest(vista='portada', fuente=fuente):
                self.assertContains(listado_html, publicacion.titulo)
                self.assertContains(listado_html, publicacion.imagen_url)

        listado = self.client.get(reverse('listar_publicaciones'))
        self.assertEqual(listado.status_code, 200)
        filas = {fila['id']: fila for fila in listado.json()['data']}
        self.assertEqual(set(filas), ids_esperados)
        for fuente, marcador in fuentes:
            fila = filas[publicaciones_por_fuente[fuente].pk]
            self.assertEqual((fila['fuente'], fila['titulo'], fila['imagen_url']), (
                fuente, publicaciones_por_fuente[fuente].titulo,
                publicaciones_por_fuente[fuente].imagen_url,
            ))

        resultados = self.client.get(
            reverse('buscar_publicaciones'), {'q': 'h45b'},
        ).json()['resultados']
        self.assertEqual({fila['id_publicacion_api'] for fila in resultados}, ids_esperados)
        for marcador, publicacion in por_marcador.items():
            individuales = self.client.get(
                reverse('buscar_publicaciones'), {'q': marcador},
            ).json()['resultados']
            self.assertEqual(
                {fila['id_publicacion_api'] for fila in individuales}, {publicacion.pk},
            )
        busqueda_html = self.client.get(reverse('buscar_noticias'), {'q': 'h45b'})
        self.assertEqual(busqueda_html.status_code, 200)
        # Las consultas individuales prueban cada marcador; la común comprueba
        # el límite de cuatro sin depender del orden elegido por relevancia.
        for marcador, publicacion in por_marcador.items():
            sugerencias = self.client.get(
                reverse('sugerencias_publicaciones'), {'q': marcador},
            ).json()['noticias']
            self.assertEqual(
                {fila['url'] for fila in sugerencias},
                {reverse('noticia', args=[publicacion.pk])},
            )
        sugerencias_comunes = self.client.get(
            reverse('sugerencias_publicaciones'), {'q': 'h45b'},
        ).json()['noticias']
        urls_esperadas = {
            reverse('noticia', args=[publicacion.pk])
            for publicacion in publicaciones_por_fuente.values()
        }
        urls_comunes = [fila['url'] for fila in sugerencias_comunes]
        self.assertEqual(len(urls_comunes), 4)
        self.assertEqual(len(set(urls_comunes)), 4)
        self.assertTrue(set(urls_comunes).issubset(urls_esperadas))
        for publicacion in publicaciones_por_fuente.values():
            self.assertContains(busqueda_html, publicacion.imagen_url)

        self.client.force_login(self.admin)
        nombre_visible = {
            'El Territorio (Misiones)': 'El Territorio',
            'Noticias del 6': 'Noticias del 6',
            'Eldorado Noticias': 'Eldorado Noticias',
            'Norte Misionero': 'Norte Misionero',
            'Fracrán Noticias': 'Fracrán Noticias',
        }
        dashboard_todos = self.client.get(reverse('dashboard'))
        self.assertEqual(dashboard_todos.status_code, 200)
        self.assertEqual(dashboard_todos.context['resumen']['total'], 5)
        self.assertEqual(
            {fila['nombre']: fila['total'] for fila in dashboard_todos.context['fuentes']},
            {visible: 1 for visible in nombre_visible.values()},
        )
        for fuente, marcador in fuentes:
            publicacion = publicaciones_por_fuente[fuente]
            visible = nombre_visible[fuente]
            filtro = 'El Territorio' if fuente == 'El Territorio (Misiones)' else fuente
            respuesta_admin = self.client.get(reverse('publicaciones'), {'fuente': filtro})
            self.assertEqual(respuesta_admin.status_code, 200)
            self.assertEqual({p.pk for p in respuesta_admin.context['publicaciones']}, {publicacion.pk})
            dashboard = self.client.get(reverse('dashboard'), {'fuente': filtro})
            self.assertEqual(dashboard.status_code, 200)
            self.assertEqual(dashboard.context['filtros']['fuente'].value(), filtro)
            self.assertEqual(dashboard.context['resumen']['total'], 1)
            self.assertEqual(
                {fila['nombre']: fila['total'] for fila in dashboard.context['fuentes']},
                {visible: 1},
            )
            polaridad = {
                'territorio45': .5,
                'del6': .25,
                'eldorado45': 0,
                'norte45': -.25,
                'fracran45': -.5,
            }[marcador]
            self.assertEqual(
                {fila['nombre']: fila['total'] for fila in dashboard.context['sentimientos']},
                {
                    'Positivo': int(polaridad > 0),
                    'Neutral': int(polaridad == 0),
                    'Negativo': int(polaridad < 0),
                },
            )

            detalle = self.client.get(reverse('noticia', args=[publicacion.pk]))
            self.assertEqual(detalle.status_code, 200)
            self.assertContains(detalle, fuente)
            self.assertContains(detalle, publicacion.imagen_url)
            self.assertContains(detalle, f'Comentario público sintético H45B {marcador}.')
            for otro_marcador, otra_publicacion in por_marcador.items():
                if otra_publicacion.pk != publicacion.pk:
                    self.assertNotContains(
                        detalle, f'Comentario público sintético H45B {otro_marcador}.',
                    )
            self.assertContains(detalle, reverse('publicaciones_etiqueta', args=[f'h45b-{marcador}']))
            self.assertEqual(
                set(detalle.context['categorias_noticia'])
                - {'Salud'},
                {categorias_por_fuente[fuente].nombre_categoria},
            )
            self.assertIn(
                etiquetas_por_fuente[fuente].pk,
                {rel.etiqueta_id for rel in detalle.context['etiquetas_noticia']},
            )
            votos_esperados = votos_por_marcador[marcador]
            valoracion_usuario = votos_esperados[0]
            self.assertEqual(detalle.context['valoracion_propia'], valoracion_usuario)
            opciones = {
                opcion['valor']: opcion['total']
                for opcion in detalle.context['valoraciones_opciones']
            }
            self.assertEqual(opciones['positivo'], votos_esperados.count('positivo'))
            self.assertEqual(opciones['negativo'], votos_esperados.count('negativo'))
            self.assertEqual(opciones['neutral'], votos_esperados.count('neutral'))
            self.assertEqual(detalle.context['valoraciones_total'], len(votos_esperados))
            self.assertEqual(
                {opcion['valor'] for opcion in detalle.context['valoraciones_opciones']
                 if opcion['seleccionada']},
                {valoracion_usuario},
            )

            etiqueta = self.client.get(
                reverse('publicaciones_etiqueta', args=[f'h45b-{marcador}']),
            )
            self.assertEqual(etiqueta.context['pagina'].paginator.count, 1)
            self.assertEqual({p.pk for p in etiqueta.context['pagina']}, {publicacion.pk})

        categoria = self.client.get(reverse('publicaciones_categoria', args=['salud']))
        self.assertEqual(categoria.context['pagina'].paginator.count, 5)
        self.assertEqual({p.pk for p in categoria.context['pagina']}, ids_esperados)

        tendencias = tendencias_destacadas()
        self.assertEqual({item['publicacion'].pk for item in tendencias}, ids_esperados)
        self.assertTrue(all(item['participaciones'] >= 2 for item in tendencias))
        categorias = next(
            grupo for grupo in noticias_destacadas_por_categoria()
            if grupo['nombre'] == 'Salud'
        )
        self.assertEqual({p.pk for p in categorias['publicaciones']}, ids_esperados)
        rankings = self.client.get(reverse('categorias'))
        self.assertEqual(rankings.status_code, 200)
        self.assertEqual(
            {p.pk for p in rankings.context['ranking_positivo']}, ids_esperados,
        )
        self.assertEqual(
            {p.pk for p in rankings.context['ranking_polemico']}, ids_esperados,
        )
        self.assertEqual(Publicacion.objects.count(), 5)

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
            'total': 24, 'articulos_completos': 24, 'fichas_rss': 0,
            'sin_cuerpo_sin_ficha': 0, 'analizadas': 2, 'pendientes': 22,
            'inconsistentes': 0,
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
