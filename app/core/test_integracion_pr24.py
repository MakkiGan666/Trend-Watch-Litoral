"""Regresiones del merge: combinar PR #24 con fechas y categorías estabilizadas.

Solo ORM de pruebas; las rutas consultadas no descargan noticias ni ejecutan IA.
Los nombres de imágenes son referencias sintéticas, sin archivos ni HTTP.
"""
from datetime import datetime, timezone

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import (
    Categoria, Comentario, Locacion, Publicacion, PublicacionGuardada,
    PublicacionTema, Tema, ValoracionPublicacion,
)


@override_settings(MEDIA_URL='/media/')
class IntegracionPR24Tests(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_superuser('integracion-editor')
        self.archivo = self.crear('archivo', 1, 20, fuente='El Territorio (Archivo)',
                                  departamento='capital', imagen_archivo='publicaciones/local.png',
                                  imagen_url='https://example.invalid/remota.png')
        self.reciente = self.crear('manual', None, 19, departamento='capital')
        self.categorias = [Categoria.objects.create(nombre_categoria=n) for n in ('Salud', 'Turismo')]
        for c in [*self.categorias, self.categorias[0]]:
            tema = Tema.objects.create(id_categoria=c, descripcion='Tema histórico')
            PublicacionTema.objects.create(id_publicacion_api=self.archivo, id_temas=tema)

    def crear(self, clave, dia_publicacion, dia_captura, **extra):
        publicacion = Publicacion.objects.create(hash_origen=clave, titulo=clave, contenido='Texto',
            fecha_publicacion=(datetime(2026, 10, dia_publicacion, 12, tzinfo=timezone.utc)
                               if dia_publicacion else None), **extra)
        Publicacion.objects.filter(pk=publicacion.pk).update(
            fecha_captura=datetime(2026, 10, dia_captura, 2, tzinfo=timezone.utc))
        publicacion.refresh_from_db()
        return publicacion

    def test_listados_combinan_imagen_subida_categorias_y_orden_efectivo(self):
        for ruta in (reverse('listar_publicaciones'), reverse('publicaciones_localidad', args=['capital'])):
            with self.subTest(ruta=ruta):
                datos = self.client.get(ruta).json()['data']
                self.assertEqual([p['id'] for p in datos], [self.reciente.pk, self.archivo.pk])
                archivo = datos[1]
                self.assertEqual(archivo['imagen_url'], '/media/publicaciones/local.png')
                self.assertEqual(archivo['categorias'], ['Salud', 'Turismo'])
                self.assertEqual(archivo['categorias_detalle'], [
                    {'id': c.pk, 'nombre': c.nombre_categoria} for c in self.categorias])
                self.assertEqual(archivo['categorias_origen'], 'asociaciones')
                self.assertEqual(archivo['fecha_efectiva'], '2026-10-01')
                self.assertEqual(archivo['fecha_precision'], 'dia')

    def test_dashboard_combina_orden_categorias_territorio_y_fecha_de_captura(self):
        self.client.force_login(self.usuario)
        Locacion.objects.create(id_publicacion_api=self.archivo, location='El Soberbio', latitud=0, longitud=0)
        respuesta = self.client.get(reverse('publicaciones'))
        publicaciones = list(respuesta.context['publicaciones'])
        self.assertEqual([p.pk for p in publicaciones], [self.reciente.pk, self.archivo.pk])
        archivo = publicaciones[1]
        self.assertEqual(archivo.categorias_navegacion, ['Salud', 'Turismo'])
        self.assertEqual(archivo.dashboard_categorias, [c.pk for c in self.categorias])
        self.assertEqual(archivo.dashboard_departamentos, ['capital', 'guarani'])
        self.assertContains(respuesta, 'data-departamentos="capital,guarani"')
        # El calendario sigue etiquetado y filtrando captura: 02 UTC es día previo local.
        self.assertContains(respuesta, 'data-capture-date="2026-10-19"')
        self.assertContains(respuesta, 'Fecha de captura')
        self.assertContains(respuesta, 'data-dashboard-edit-toggle')
        self.assertContains(respuesta, 'Sin categoría asociada')

    def test_detalle_conserva_precision_y_funciones_sociales_y_guardados(self):
        self.client.force_login(self.usuario)
        Comentario.objects.create(publicacion=self.archivo, autor=self.usuario, texto='Opinión integrada')
        ValoracionPublicacion.objects.create(publicacion=self.archivo, usuario=self.usuario, sentimiento='positivo')
        PublicacionGuardada.objects.create(publicacion=self.archivo, usuario=self.usuario)
        respuesta = self.client.get(reverse('noticia', args=[self.archivo.pk]))
        self.assertContains(respuesta, 'Hora no verificada')
        self.assertContains(respuesta, 'datetime="2026-10-01"')
        self.assertContains(respuesta, '/media/publicaciones/local.png')
        self.assertContains(respuesta, 'Opinión integrada')
        self.assertContains(respuesta, 'Sección: Archivo')
        self.assertEqual(respuesta.context['categorias_noticia'], ['Salud', 'Turismo'])
        self.assertTrue(respuesta.context['noticia_guardada'])
        self.assertEqual(respuesta.context['valoraciones_total'], 1)
        self.archivo.refresh_from_db()
        self.assertEqual(self.archivo.fecha_publicacion.hour, 12)
        self.assertEqual(self.archivo.temas.count(), 3)

    def test_sin_asociaciones_no_inventa_sociedad_y_conserva_fallback_de_imagen(self):
        self.reciente.fuente = 'El Territorio (Sociedad)'
        self.reciente.imagen_url = 'https://example.invalid/imagen.png'
        self.reciente.save(update_fields=['fuente', 'imagen_url'])
        datos = self.client.get(reverse('listar_publicaciones')).json()['data'][0]
        self.assertEqual(datos['categorias'], ['Sociedad'])  # Campo legacy de sección.
        self.assertEqual(datos['categorias_detalle'], [])  # Autoritativo para frontend nuevo.
        self.assertEqual(datos['categorias_origen'], 'seccion')
        self.assertEqual(datos['imagen_url'], self.reciente.imagen_url)
        respuesta = self.client.get(reverse('noticia', args=[self.reciente.pk]))
        self.assertEqual(respuesta.context['categorias_noticia'], [])
        self.assertContains(respuesta, 'Sin categoría asociada')
