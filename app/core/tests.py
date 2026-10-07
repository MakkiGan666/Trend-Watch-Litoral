from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate
from unittest.mock import patch
from core.models import Publicacion, RegistroDatos, Sentimiento
from core.views import crear_o_ingestar_publicacion, disparar_ingesta

# Create your tests here.

class IngestaTestCase(TestCase):
    def setUp(self):
        self.registro = RegistroDatos.objects.create(
            fuentes_api="Prueba Feed",
            fecha_ejecucion=timezone.now(),
            estado="EXITO",
            lenguaje="es"
        )

    def test_crear_publicacion(self):
        pub = Publicacion.objects.create(
            hash_origen="hash123test",
            fuente="El Territorio",
            titulo="Noticia de Prueba",
            contenido="Contenido de prueba",
            url="https://ejemplo.com",
            id_registro=self.registro
        )
        self.assertEqual(pub.titulo, "Noticia de Prueba")
        self.assertFalse(pub.procesado_ia)


class IngestaRSSTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = get_user_model()(username='prueba_ingesta')
        self.registro = RegistroDatos.objects.create(
            fuentes_api='Prueba RSS', fecha_ejecucion=timezone.now(),
            estado='EXITO', lenguaje='es',
        )
        self.resumen = {
            'status': 'EXITO', 'capturados': 1,
            'registro_id': self.registro.pk,
        }

    def request(self, ruta):
        request = self.factory.post(ruta, {}, format='json')
        force_authenticate(request, user=self.user)
        return request

    @patch('core.views.compute_probabilistic_sentiment', return_value={'confidence_score': 0.8})
    @patch('core.views.analyze_sentiment_lexicon', return_value=0.5)
    @patch('core.views.fetch_and_store_elterritorio')
    def test_rss_procesa_solo_publicaciones_del_registro(self, scraper, lexicon, probabilistico):
        nueva = Publicacion.objects.create(
            hash_origen='nueva', titulo='Noticia', contenido='Contenido',
            id_registro=self.registro,
        )
        anterior = Publicacion.objects.create(hash_origen='anterior', contenido='Anterior')
        procesada = Publicacion.objects.create(
            hash_origen='procesada', contenido='Procesada',
            id_registro=self.registro, procesado_ia=True,
        )
        scraper.return_value = dict(self.resumen, capturados=2)

        response = crear_o_ingestar_publicacion(self.request('/api/publicaciones/crear/'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['total_ingestadas'], 2)
        nueva.refresh_from_db()
        anterior.refresh_from_db()
        self.assertTrue(nueva.procesado_ia)
        self.assertFalse(anterior.procesado_ia)
        self.assertEqual(Sentimiento.objects.get(id_publicacion_api=nueva).polaridad, 0.5)
        self.assertFalse(Sentimiento.objects.filter(id_publicacion_api=anterior).exists())
        self.assertFalse(Sentimiento.objects.filter(id_publicacion_api=procesada).exists())
        lexicon.assert_called_once_with('Noticia Contenido')
        probabilistico.assert_called_once()

    @patch('core.views.analyze_sentiment_lexicon')
    @patch('core.views.fetch_and_store_elterritorio')
    def test_rss_sin_capturas_devuelve_total_cero(self, scraper, lexicon):
        scraper.return_value = dict(self.resumen, capturados=0)
        response = crear_o_ingestar_publicacion(self.request('/api/publicaciones/crear/'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['total_ingestadas'], 0)
        lexicon.assert_not_called()

    @patch('core.views.procesar_publicaciones_con_ia')
    @patch('core.views.compute_probabilistic_sentiment')
    @patch('core.views.analyze_sentiment_lexicon')
    @patch('core.views.fetch_and_store_elterritorio')
    def test_error_ingesta_detiene_ambas_rutas(self, scraper, lexicon, probabilistico, ia):
        parcial = Publicacion.objects.create(
            hash_origen='parcial', contenido='Guardada antes del error',
            id_registro=self.registro,
        )
        scraper.return_value = {'status': 'ERROR', 'detalle': 'Feed no disponible'}
        for vista, argumentos in ((crear_o_ingestar_publicacion, ()), (disparar_ingesta, ('misiones',))):
            with self.subTest(vista=vista.__name__):
                response = vista(self.request('/api/publicaciones/crear/'), *argumentos)
                self.assertEqual(response.status_code, 500)
                self.assertEqual(response.data['status'], 'error')
                self.assertEqual(response.data['mensaje_ingesta'], scraper.return_value)
        lexicon.assert_not_called()
        probabilistico.assert_not_called()
        ia.assert_not_called()
        parcial.refresh_from_db()
        self.assertFalse(parcial.procesado_ia)
        self.assertFalse(Sentimiento.objects.exists())

    @patch('core.views.procesar_publicaciones_con_ia', return_value='Análisis completado')
    @patch('core.views.fetch_and_store_elterritorio')
    def test_ingesta_categoria_exitosa_continua_con_ia(self, scraper, ia):
        scraper.return_value = self.resumen
        response = disparar_ingesta(self.request('/api/publicaciones/ingestar/misiones/'), 'misiones')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'success')
        self.assertEqual(response.data['mensaje_ingesta'], self.resumen)
        scraper.assert_called_once_with('misiones')
        ia.assert_called_once_with(batch_size=10)
