from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from core.models import Publicacion


class RecuperarImagenesTests(TestCase):
    def setUp(self):
        self.noticia = Publicacion.objects.create(hash_origen='recuperar', fuente='El Territorio (Policiales)', titulo='Noticia', contenido='Texto', url='https://www.elterritorio.com.ar/noticias/nota')

    @patch('core.management.commands.recuperar_imagenes.descargar', return_value=b'<meta property="og:image" content="/foto.jpg">')
    def test_simulacion_y_actualizacion_solo_imagen(self, descargar):
        call_command('recuperar_imagenes', stdout=StringIO())
        self.noticia.refresh_from_db()
        self.assertEqual(self.noticia.imagen_url, '')
        antes = Publicacion.objects.values().get(pk=self.noticia.pk)
        call_command('recuperar_imagenes', aplicar=True, stdout=StringIO())
        despues = Publicacion.objects.values().get(pk=self.noticia.pk)
        self.assertEqual(despues.pop('imagen_url'), 'https://www.elterritorio.com.ar/foto.jpg')
        antes.pop('imagen_url')
        self.assertEqual(antes, despues)
        call_command('recuperar_imagenes', aplicar=True, stdout=StringIO())
        self.assertEqual(descargar.call_count, 2)

    @patch('core.management.commands.recuperar_imagenes.descargar')
    def test_conserva_foto_manual_y_rechaza_destino_ajeno(self, descargar):
        self.noticia.imagen_archivo = 'publicaciones/manual.jpg'
        self.noticia.save()
        call_command('recuperar_imagenes', aplicar=True, stdout=StringIO())
        descargar.assert_not_called()
        self.noticia.imagen_archivo = ''
        self.noticia.url = 'http://127.0.0.1/privado'
        self.noticia.save()
        call_command('recuperar_imagenes', aplicar=True, stdout=StringIO(), stderr=StringIO())
        descargar.assert_not_called()

    @patch('core.management.commands.recuperar_imagenes.descargar', return_value=b'<meta property="og:image" content="javascript:alert(1)">')
    def test_sin_imagen_no_modifica_registro(self, descargar):
        call_command('recuperar_imagenes', aplicar=True, stdout=StringIO())
        self.noticia.refresh_from_db()
        self.assertEqual(self.noticia.imagen_url, '')
