from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.imagenes import es_portada_generica
from core.models import Publicacion
from core.services.scraper import _imagen_valida


URL_GENERICA = 'https://www.elterritorio.com.ar/images/custom/sin-imagen.webp?_v=v3-610'


class PortadaGenericaTests(SimpleTestCase):
    def test_distingue_placa_generica_de_foto_real(self):
        self.assertTrue(es_portada_generica(URL_GENERICA))
        self.assertFalse(es_portada_generica('https://www.elterritorio.com.ar/images/foto.webp'))
        self.assertFalse(es_portada_generica('https://otro-medio.com/images/custom/sin-imagen.webp'))
        self.assertEqual(_imagen_valida(URL_GENERICA), '')


class PortadaGenericaEnVistasTests(TestCase):
    def test_placa_guardada_no_se_muestra_como_foto_en_listado_ni_detalle(self):
        noticia = Publicacion.objects.create(
            hash_origen='placa-generica', titulo='Noticia sin foto propia',
            contenido='Contenido de prueba.', imagen_url=URL_GENERICA,
        )
        self.assertEqual(noticia.imagen_publica_url, '')
        detalle = self.client.get(reverse('noticia', args=[noticia.pk]))
        self.assertContains(detalle, 'Imagen no disponible')
        self.assertNotContains(detalle, 'sin-imagen.webp')
