"""Validación de dependencias y contratos de Fase 1.2. Todo contenido es local."""
from contextlib import ExitStack
import json
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, RequestFactory
from rest_framework.test import APIClient


class NewspaperLocalTestCase(SimpleTestCase):
    def test_html_local_sin_descargas_de_articulo_imagenes_ni_dns(self):
        # Importar realmente la dependencia: ausencia/incompatibilidad debe fallar.
        from newspaper import Article
        from core.services import scraper

        url = 'https://www.elterritorio.com.ar/noticias/2026/10/20/900300-local'
        parrafos = [
            'La comunidad de Posadas presentó un programa cultural para los barrios. '
            'Las actividades incluyen talleres de lectura y encuentros abiertos a las familias. '
            'La propuesta se realizará durante la semana con participación de artistas locales.',
            'Las instituciones educativas organizaron recorridos y charlas en espacios públicos. '
            'Los responsables explicaron los horarios de cada actividad y la forma de inscripción. '
            'El proyecto busca ampliar el acceso de los vecinos a las propuestas culturales.',
            'El encuentro final tendrá lugar en la plaza central de la ciudad. '
            'Los organizadores confirmaron que la entrada será gratuita para todas las personas. '
            'Los participantes podrán compartir sus trabajos y conversar con los coordinadores.',
        ]
        html = ('<!doctype html><html lang="es"><head><meta charset="utf-8">'
                '<title>Encuentro cultural en Posadas</title>'
                '<meta property="og:image" content="https://imagenes.invalid/foto.jpg">'
                '</head><body><article><h1>Encuentro cultural en Posadas</h1>'
                + ''.join('<p>' + p + '</p>' for p in parrafos)
                + '<img src="https://imagenes.invalid/foto.jpg"></article></body></html>').encode()
        intentos = []

        def rechazar(*args, **kwargs):
            intentos.append('red')
            raise AssertionError('Intento de red durante el parseo local')

        with ExitStack() as stack:
            for objetivo in (
                'socket.socket.connect', 'socket.socket.connect_ex', 'socket.getaddrinfo',
                'socket.gethostbyname', 'socket.gethostbyname_ex',
                'requests.sessions.Session.request', 'urllib.request.urlopen',
            ):
                stack.enter_context(patch(objetivo, side_effect=rechazar))
            descarga = stack.enter_context(patch.object(scraper, '_descargar', return_value=html))
            # El wrapper permite comprobar que no se usó el fallback del servicio.
            constructor = stack.enter_context(patch.object(scraper, 'Article', wraps=Article))
            articulo = scraper._leer_articulo(url)
            self.assertIsNotNone(articulo)
            self.assertIsInstance(articulo, Article)
            self.assertEqual(articulo.title, 'Encuentro cultural en Posadas')
            self.assertIn('La comunidad de Posadas', articulo.text)
            self.assertIn('entrada será gratuita', articulo.text)
            self.assertFalse(articulo.config.fetch_images)
            descarga.assert_called_once_with(url)
            constructor.assert_called_once_with(url, language='es', fetch_images=False)
        # Detecta también intentos de red que newspaper haya capturado internamente.
        self.assertEqual(intentos, [])


class ConsumidoresIngestaFase12TestCase(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_superuser(username='fase12-consumidor')
        self.api = APIClient()
        self.api.force_authenticate(self.usuario)

    def test_parcial_y_fallo_detienen_api_y_endpoint_alternativo(self):
        from core.services.gemini_cliente import disparar_ingesta as alternativa
        for estado in ('PARCIAL', 'FALLO'):
            resumen = {'status': 'ERROR', 'estado': estado, 'cobertura_completa': False,
                       'capturados': int(estado == 'PARCIAL'), 'detalle': 'Cobertura incompleta'}
            for destino in ('core.views', 'core.services.gemini_cliente'):
                with self.subTest(estado=estado, destino=destino), patch(
                    destino + '.fetch_and_store_elterritorio', return_value=resumen
                ), patch(destino + '.procesar_publicaciones_con_ia') as ia:
                    if destino == 'core.views':
                        respuesta = self.api.post('/api/publicaciones/ingestar/misiones/')
                        datos = respuesta.json()
                    else:
                        request = RequestFactory().post('/alternativa/')
                        request.user = self.usuario
                        respuesta = alternativa(request, 'misiones')
                        datos = json.loads(respuesta.content)
                    self.assertEqual(respuesta.status_code, 500)
                    self.assertEqual(datos['mensaje_ingesta'], resumen)
                    ia.assert_not_called()

    def test_pipeline_conserva_contrato_de_los_cinco_estados(self):
        for estado in ('EXITO', 'SIN_RESULTADOS', 'DUPLICADOS', 'PARCIAL', 'FALLO'):
            completa = estado in ('EXITO', 'SIN_RESULTADOS', 'DUPLICADOS')
            resumen = {'status': 'EXITO' if completa else 'ERROR', 'estado': estado,
                       'cobertura_completa': completa, 'capturados': int(estado == 'EXITO'),
                       'detalle': 'Cobertura incompleta'}
            salida = StringIO()
            with self.subTest(estado=estado), patch(
                'core.management.commands.run_pipeline.fetch_and_store_elterritorio', return_value=resumen
            ), patch('core.management.commands.run_pipeline.procesar_publicaciones_con_ia', return_value={
                'estado': 'SIN_PENDIENTES', 'mensaje': 'Sin pendientes',
            }) as ia:
                if completa:
                    call_command('run_pipeline', stdout=salida)
                    ia.assert_called_once_with(batch_size=10)
                    self.assertIn('Pipeline completado exitosamente.', salida.getvalue())
                else:
                    with self.assertRaises(CommandError):
                        call_command('run_pipeline', stdout=salida)
                    ia.assert_not_called()
                    self.assertNotIn('Pipeline completado exitosamente.', salida.getvalue())
