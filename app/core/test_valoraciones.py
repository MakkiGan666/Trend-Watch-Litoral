from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse

from core.models import Publicacion, Sentimiento, ValoracionPublicacion


class ValoracionesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user('lector_valoracion', password='test-only-password')
        cls.otro = get_user_model().objects.create_user('otro_valoracion', password='test-only-password')
        cls.noticia = Publicacion.objects.create(hash_origen='valoracion-prueba', titulo='Noticia', contenido='Texto')

    def enviar(self, sentimiento, **extra):
        return self.client.post(reverse('valorar_noticia', args=[self.noticia.pk]), {'sentimiento': sentimiento, **extra})

    def test_totales_publicos_y_ausencia_no_equivale_a_neutral(self):
        ValoracionPublicacion.objects.create(publicacion=self.noticia, usuario=self.otro, sentimiento='positivo')
        response = self.client.get(reverse('noticia', args=[self.noticia.pk]))
        opciones = {op['valor']: op for op in response.context['valoraciones_opciones']}
        self.assertEqual(response.context['valoraciones_total'], 1)
        self.assertIsNone(response.context['valoracion_propia'])
        self.assertEqual(opciones['neutral']['total'], 0)
        self.assertContains(response, 'Ingresar para valorar')

    def test_anonimo_get_y_csrf_no_pueden_escribir(self):
        self.assertEqual(self.enviar('positivo').status_code, 302)
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.get(reverse('valorar_noticia', args=[self.noticia.pk])).status_code, 405)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.usuario)
        self.assertEqual(client.post(reverse('valorar_noticia', args=[self.noticia.pk]), {'sentimiento': 'positivo'}).status_code, 403)
        self.assertFalse(ValoracionPublicacion.objects.exists())

    def test_cambiar_repetir_y_retirar_sin_duplicar(self):
        self.client.force_login(self.usuario)
        for sentimiento in ['positivo', 'positivo', 'neutral', 'negativo']:
            response = self.enviar(sentimiento)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(ValoracionPublicacion.objects.count(), 1)
            self.assertEqual(ValoracionPublicacion.objects.get().sentimiento, sentimiento)
        self.assertContains(self.client.get(reverse('noticia', args=[self.noticia.pk])), 'Tu elección')
        self.assertEqual(self.enviar('retirar').status_code, 302)
        self.assertEqual(self.enviar('retirar').status_code, 302)
        self.assertFalse(ValoracionPublicacion.objects.exists())

    def test_usuario_fijado_por_sesion_y_no_se_altera_la_ia(self):
        ValoracionPublicacion.objects.create(publicacion=self.noticia, usuario=self.otro, sentimiento='positivo')
        analisis = Sentimiento.objects.create(id_publicacion_api=self.noticia, polaridad=.5, confianza=.8)
        self.client.force_login(self.usuario)
        self.enviar('negativo', usuario=self.otro.pk)
        self.assertEqual(ValoracionPublicacion.objects.filter(publicacion=self.noticia).count(), 2)
        self.enviar('retirar', usuario=self.otro.pk)
        self.assertEqual(ValoracionPublicacion.objects.get().usuario_id, self.otro.pk)
        analisis.refresh_from_db()
        self.assertEqual(analisis.polaridad, .5)
        self.assertEqual(analisis.confianza, .8)

    def test_invalido_y_noticia_inexistente(self):
        self.client.force_login(self.usuario)
        for sentimiento in ['', 'malo', 'POSITIVO', 'positivo,neutral']:
            self.assertEqual(self.enviar(sentimiento).status_code, 400)
        self.assertEqual(self.client.post(reverse('valorar_noticia', args=[999999]), {'sentimiento': 'positivo'}).status_code, 404)
        self.assertFalse(ValoracionPublicacion.objects.exists())

    def test_base_impide_duplicados_y_sentimientos_invalidos(self):
        ValoracionPublicacion.objects.create(publicacion=self.noticia, usuario=self.usuario, sentimiento='positivo')
        with self.assertRaises(IntegrityError), transaction.atomic():
            ValoracionPublicacion.objects.create(publicacion=self.noticia, usuario=self.usuario, sentimiento='neutral')
        with self.assertRaises(IntegrityError), transaction.atomic():
            ValoracionPublicacion.objects.create(publicacion=self.noticia, usuario=self.otro, sentimiento='otro')
        self.assertEqual(ValoracionPublicacion.objects.count(), 1)

    def test_valoracion_se_limita_a_su_noticia(self):
        otra = Publicacion.objects.create(hash_origen='otra-valoracion', titulo='Otra noticia', contenido='Otro texto')
        ValoracionPublicacion.objects.create(publicacion=otra, usuario=self.usuario, sentimiento='neutral')
        self.client.force_login(self.usuario)
        self.enviar('positivo')
        response = self.client.get(reverse('noticia', args=[self.noticia.pk]))
        self.assertEqual(response.context['valoraciones_total'], 1)
        self.assertEqual(response.context['valoracion_propia'], 'positivo')
        self.assertEqual(ValoracionPublicacion.objects.filter(publicacion=otra).get().sentimiento, 'neutral')
