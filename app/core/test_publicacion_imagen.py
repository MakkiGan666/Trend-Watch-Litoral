from unittest.mock import patch
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from core.models import Publicacion


class ImagenFormularioPublicacionTests(TestCase):
    def setUp(self):
        carpeta = TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        self.media = carpeta.name
        ajuste = override_settings(MEDIA_ROOT=self.media)
        ajuste.enable()
        self.addCleanup(ajuste.disable)
        user = get_user_model().objects.create_superuser('editor_imagen', password='test-only-password')
        self.client.force_login(user)
        self.data = {'titulo': 'Noticia de prueba', 'contenido': 'Contenido', 'fuente': 'Medio',
                     'url': 'https://example.com/noticia', 'imagen_url': 'https://example.com/foto.jpg'}

    @patch('core.views._analizar_y_guardar_sentimiento')
    def test_crear_guarda_imagen_y_editar_permite_cambiarla_o_quitarla(self, analizar):
        response = self.client.post(reverse('crear_publicacion_web'), self.data)
        self.assertRedirects(response, reverse('publicaciones'), fetch_redirect_response=False)
        publicacion = Publicacion.objects.get()
        self.assertEqual(publicacion.imagen_url, self.data['imagen_url'])
        analizar.reset_mock()
        for imagen in ['https://example.com/otra.webp', '']:
            response = self.client.post(reverse('editar_publicacion_web', args=[publicacion.pk]),
                                        {**self.data, 'imagen_url': imagen})
            self.assertRedirects(response, reverse('publicaciones'), fetch_redirect_response=False)
            publicacion.refresh_from_db()
            self.assertEqual(publicacion.imagen_url, imagen)
        analizar.assert_not_called()

    @patch('core.views._analizar_y_guardar_sentimiento')
    def test_imagen_invalida_no_crea_publicacion(self, analizar):
        for imagen in ['no-es-url', 'ftp://example.com/foto.jpg', 'javascript:alert(1)']:
            with self.subTest(imagen=imagen):
                response = self.client.post(reverse('crear_publicacion_web'), {**self.data, 'imagen_url': imagen})
                self.assertEqual(response.status_code, 200)
                self.assertIn('imagen_url', response.context['form'].errors)
        self.assertFalse(Publicacion.objects.exists())
        analizar.assert_not_called()

    @patch('core.views._analizar_y_guardar_sentimiento')
    def test_crear_sin_imagen_sigue_siendo_valido(self, analizar):
        response = self.client.post(reverse('crear_publicacion_web'), {**self.data, 'imagen_url': ''})
        self.assertRedirects(response, reverse('publicaciones'), fetch_redirect_response=False)
        self.assertEqual(Publicacion.objects.get().imagen_url, '')

    def archivo(self):
        buffer = BytesIO()
        Image.new('RGB', (8, 8), 'green').save(buffer, 'PNG')
        return SimpleUploadedFile('foto.png', buffer.getvalue(), content_type='image/png')

    @patch('core.views._analizar_y_guardar_sentimiento')
    def test_subida_se_guarda_y_se_expone_en_tarjeta_y_detalle(self, analizar):
        response = self.client.post(reverse('crear_publicacion_web'),
                                    {**self.data, 'imagen_archivo': self.archivo()})
        self.assertEqual(response.status_code, 302)
        publicacion = Publicacion.objects.get()
        self.assertTrue(Path(publicacion.imagen_archivo.path).is_file())
        self.assertTrue(publicacion.imagen_publica_url.startswith('/media/publicaciones/'))
        listado = self.client.get(reverse('listar_publicaciones')).json()
        self.assertEqual(listado['data'][0]['imagen_url'], publicacion.imagen_publica_url)
        self.assertContains(self.client.get(reverse('noticia', args=[publicacion.pk])), publicacion.imagen_publica_url)

    @patch('core.views._analizar_y_guardar_sentimiento')
    def test_editar_conserva_reemplaza_y_quita_archivo(self, analizar):
        self.client.post(reverse('crear_publicacion_web'), {**self.data, 'imagen_archivo': self.archivo()})
        publicacion = Publicacion.objects.get()
        ruta = publicacion.imagen_archivo.name
        editar = reverse('editar_publicacion_web', args=[publicacion.pk])
        self.client.post(editar, self.data)
        publicacion.refresh_from_db()
        self.assertEqual(publicacion.imagen_archivo.name, ruta)
        self.client.post(editar, {**self.data, 'imagen_archivo': self.archivo()})
        publicacion.refresh_from_db()
        self.assertNotEqual(publicacion.imagen_archivo.name, ruta)
        self.client.post(editar, {**self.data, 'imagen_archivo-clear': 'on'})
        publicacion.refresh_from_db()
        self.assertFalse(publicacion.imagen_archivo)
        self.assertEqual(publicacion.imagen_publica_url, self.data['imagen_url'])

    @patch('core.views._analizar_y_guardar_sentimiento')
    def test_archivo_falso_o_grande_no_crea_publicacion(self, analizar):
        grande = self.archivo()
        grande.size = 5 * 1024 * 1024 + 1
        falso = SimpleUploadedFile('imagen.png', b'no es una imagen', content_type='image/png')
        for archivo in [falso, grande]:
            with self.subTest(nombre=archivo.name):
                # Validar el tamaño sin transmitir 5 MB al servidor de pruebas.
                from core.forms import PublicacionForm
                form = PublicacionForm(data=self.data, files={'imagen_archivo': archivo})
                self.assertFalse(form.is_valid())
                self.assertIn('imagen_archivo', form.errors)
        self.assertFalse(Publicacion.objects.exists())
        analizar.assert_not_called()
