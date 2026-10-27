"""El panel de gestión consulta todos los registros y pagina sólo la tabla."""

from datetime import datetime, timezone

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.models import Categoria, Locacion, Publicacion, PublicacionTema, Sentimiento, Tema


class PublicacionesPaginacionTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.administrador = get_user_model().objects.create_superuser(
            username='administrador_panel', password='clave-de-prueba',
        )
        cls.publicaciones = []
        for numero in range(31):
            captura = datetime(2026, 10, 27, 12, numero, tzinfo=timezone.utc)
            cls.publicaciones.append(Publicacion.objects.create(
                hash_origen=f'panel-paginado-{numero}',
                titulo='Único titular buscable' if numero == 0 else f'Noticia {numero}',
                contenido='Texto de prueba',
                fuente='Manual' if numero == 0 else 'El Territorio (Archivo)',
                fecha_publicacion=datetime(2026, 1, 15, 12, tzinfo=timezone.utc) if numero == 0 else None,
                fecha_captura=captura,
                departamento='capital' if numero == 0 else '',
            ))
        categoria = Categoria.objects.create(nombre_categoria='Salud')
        tema = Tema.objects.create(id_categoria=categoria, descripcion='Salud de prueba')
        PublicacionTema.objects.create(id_publicacion_api=cls.publicaciones[0], id_temas=tema)
        cls.categoria = categoria
        Locacion.objects.create(
            id_publicacion_api=cls.publicaciones[1], location='Posadas', latitud=-27.36, longitud=-55.89,
        )
        Sentimiento.objects.create(
            id_publicacion_api=cls.publicaciones[0], polaridad=0.5, confianza=0.8,
        )

    def setUp(self):
        self.client.force_login(self.administrador)

    def test_resumen_global_y_tabla_paginada(self):
        respuesta = self.client.get('/publicaciones/')
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context['resumen'], {
            'total': 31, 'analizadas': 1, 'pendientes': 30,
        })
        self.assertEqual(respuesta.context['total_global'], 31)
        self.assertEqual(len(respuesta.context['publicaciones']), 25)
        self.assertContains(respuesta, 'Siguiente')
        self.assertContains(respuesta, 'Fecha de publicación')
        segunda = self.client.get('/publicaciones/?page=2')
        self.assertEqual(len(segunda.context['publicaciones']), 6)
        self.assertIn(self.publicaciones[0], segunda.context['publicaciones'])

    def test_busqueda_y_filtros_toman_en_cuenta_noticias_fuera_de_la_primera_pagina(self):
        casos = (
            ({'q': 'unico'}, 1),
            ({'fuente': 'Manual'}, 1),
            ({'categoria': str(self.categoria.pk)}, 1),
            ({'categoria': '__missing'}, 30),
            ({'localidad': 'capital'}, 2),
            ({'localidad': '__missing'}, 29),
            ({'fecha': '2026-01-15'}, 1),
            ({'fecha': '2026-10-27'}, 30),
            ({'fecha': '2026-01-15', 'localidad': 'capital'}, 1),
            ({'q': 'unico', 'fuente': 'El Territorio'}, 0),
        )
        for filtros, total in casos:
            with self.subTest(filtros=filtros):
                respuesta = self.client.get('/publicaciones/', filtros)
                self.assertEqual(respuesta.status_code, 200)
                self.assertEqual(respuesta.context['resumen']['total'], total)
                self.assertEqual(respuesta.context['total_global'], 31)

    def test_filtros_invalidos_no_muestran_todo_el_archivo(self):
        for filtros in ({'fecha': '2025-01-01'}, {'categoria': '99999'}, {'localidad': 'inventada'}):
            with self.subTest(filtros=filtros):
                respuesta = self.client.get('/publicaciones/', filtros)
                self.assertEqual(respuesta.status_code, 200)
                self.assertEqual(respuesta.context['resumen']['total'], 0)
                self.assertTrue(respuesta.context['filtros'].errors)
