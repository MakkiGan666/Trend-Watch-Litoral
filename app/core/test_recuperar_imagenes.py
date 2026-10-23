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

    def otra_noticia(self, clave):
        return Publicacion.objects.create(hash_origen=clave, fuente='Policiales', titulo=clave,
                                          contenido='Texto', url=f'https://www.elterritorio.com.ar/{clave}')

    def test_cursor_alcanza_recuperable_tras_cien_irrecuperables(self):
        for i in range(99):
            self.otra_noticia(f'irrecuperable-{i}')
        ultima = self.otra_noticia('recuperable')
        cursor = Publicacion.objects.order_by('pk')[99].pk
        def documento(url, **kwargs):
            if url == ultima.url:
                return b'<meta property="og:image" content="/foto.jpg">'
            return b'<html></html>'
        with patch('core.management.commands.recuperar_imagenes.descargar', side_effect=documento) as descargar:
            salida = StringIO()
            call_command('recuperar_imagenes', limite=100, aplicar=True, stdout=salida)
            self.assertEqual(descargar.call_count, 100)
            self.assertIn(f'--despues-de-id={cursor}', salida.getvalue())
            salida = StringIO()
            call_command('recuperar_imagenes', limite=100, despues_de_id=cursor, aplicar=True, stdout=salida)
            self.assertEqual(descargar.call_count, 101)
            self.assertIn('Fin del conjunto', salida.getvalue())
            call_command('recuperar_imagenes', despues_de_id=ultima.pk, stdout=StringIO())
            self.assertEqual(descargar.call_count, 101)
        ultima.refresh_from_db()
        self.assertEqual(ultima.imagen_url, 'https://www.elterritorio.com.ar/foto.jpg')
        self.assertEqual(Publicacion.objects.filter(imagen_url='').count(), 100)

    def test_cursor_con_limite_uno_y_simulacion_no_escribe(self):
        segunda = self.otra_noticia('segunda')
        antes = list(Publicacion.objects.order_by('pk').values())
        with patch('core.management.commands.recuperar_imagenes.descargar', side_effect=[b'', b'<meta property="og:image" content="/foto.jpg">']) as descargar:
            call_command('recuperar_imagenes', limite=1, stdout=StringIO())
            call_command('recuperar_imagenes', limite=1, despues_de_id=self.noticia.pk, stdout=StringIO())
            self.assertEqual(descargar.call_args.args[0], segunda.url)
        self.assertEqual(list(Publicacion.objects.order_by('pk').values()), antes)

    def test_errores_http_continuan_lote_e_informan_resumen(self):
        from http.client import BadStatusLine, IncompleteRead
        segunda = self.otra_noticia('segunda')
        for error in (BadStatusLine('broken'), IncompleteRead(b'parcial', 100)):
            with self.subTest(error=type(error).__name__):
                Publicacion.objects.filter(pk=segunda.pk).update(imagen_url='')
                salida, diagnostico = StringIO(), StringIO()
                with patch('core.management.commands.recuperar_imagenes.descargar', side_effect=[error, b'<meta property="og:image" content="/foto.jpg">']) as descargar:
                    call_command('recuperar_imagenes', aplicar=True, stdout=salida, stderr=diagnostico)
                self.assertEqual(descargar.call_count, 2)
                segunda.refresh_from_db()
                self.assertEqual(segunda.imagen_url, 'https://www.elterritorio.com.ar/foto.jpg')
                self.assertIn(f'#{self.noticia.pk}: no se pudo recuperar ({type(error).__name__})', diagnostico.getvalue())
                self.assertIn('Actualizadas: 1.', salida.getvalue())
                self.assertIn('Intentadas: 2. Errores: 1.', salida.getvalue())
                self.assertIn(f'Cursor: {segunda.pk}.', salida.getvalue())

    def test_foto_manual_agregada_durante_descarga_se_preserva(self):
        def documento(*args, **kwargs):
            Publicacion.objects.filter(pk=self.noticia.pk).update(imagen_archivo='publicaciones/manual.jpg')
            return b'<meta property="og:image" content="/foto.jpg">'
        with patch('core.management.commands.recuperar_imagenes.descargar', side_effect=documento):
            call_command('recuperar_imagenes', aplicar=True, stdout=StringIO())
        self.noticia.refresh_from_db()
        self.assertEqual(self.noticia.imagen_url, '')
        self.assertEqual(self.noticia.imagen_archivo.name, 'publicaciones/manual.jpg')

    def test_errores_de_programacion_y_base_se_propagan(self):
        from django.db import OperationalError
        with patch('core.management.commands.recuperar_imagenes.descargar', side_effect=TypeError('programacion')):
            with self.assertRaises(TypeError):
                call_command('recuperar_imagenes', stdout=StringIO())
        with patch('core.management.commands.recuperar_imagenes.descargar', return_value=b'<meta property="og:image" content="/foto.jpg">'):
            with patch('django.db.models.query.QuerySet.update', side_effect=OperationalError('persistencia')):
                with self.assertRaises(OperationalError):
                    call_command('recuperar_imagenes', aplicar=True, stdout=StringIO())

    def test_limites_y_cursor_invalidos_no_descargan(self):
        from django.core.management.base import CommandError
        with patch('core.management.commands.recuperar_imagenes.descargar') as descargar:
            for opciones in ({'limite': 0}, {'limite': 101}, {'despues_de_id': -1}):
                with self.subTest(opciones=opciones), self.assertRaises(CommandError):
                    call_command('recuperar_imagenes', stdout=StringIO(), **opciones)
            descargar.assert_not_called()
