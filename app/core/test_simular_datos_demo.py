from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings

from core.models import ClicPublicacion, Comentario, Publicacion, ValoracionPublicacion


@override_settings(DEBUG=True)
class SimularDatosDemoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.publicacion = Publicacion.objects.create(
            hash_origen='simulacion-demo-prueba',
            titulo='Una noticia local para la prueba',
            contenido='Texto de prueba.',
        )

    def ejecutar(self, **opciones):
        opciones = {
            'usuarios': 5,
            'votos_por_publicacion': 3,
            'comentarios_por_publicacion': 2,
            'clics_por_publicacion': 4,
            'limite': 0,
            'desde_id': 0,
            'tamano_lote': 10,
            'semilla': 123,
            'aplicar': False,
            **opciones,
        }
        salida = StringIO()
        call_command('simular_datos_demo', stdout=salida, **opciones)
        return salida.getvalue()

    def test_previsualizar_no_crea_registros(self):
        salida = self.ejecutar()

        self.assertIn('Previsualización: no se escribió nada', salida)
        self.assertEqual(get_user_model().objects.filter(username__startswith='demo_sim_').count(), 0)
        self.assertFalse(ValoracionPublicacion.objects.exists())
        self.assertFalse(Comentario.objects.exists())
        self.assertFalse(ClicPublicacion.objects.exists())

    def test_aplicar_crea_cuentas_inactivas_y_actividad_idempotente(self):
        self.ejecutar(aplicar=True)

        cuentas = list(get_user_model().objects.filter(
            username__startswith='demo_sim_',
        ).order_by('username'))
        self.assertEqual(len(cuentas), 5)
        self.assertTrue(all(not cuenta.is_active and not cuenta.is_staff for cuenta in cuentas))
        self.assertTrue(all(not cuenta.has_usable_password() for cuenta in cuentas))
        self.assertEqual(ValoracionPublicacion.objects.count(), 3)
        self.assertEqual(
            set(ValoracionPublicacion.objects.values_list('sentimiento', flat=True)),
            set(ValoracionPublicacion.Sentimiento.values),
        )
        self.assertEqual(Comentario.objects.count(), 2)
        self.assertTrue(all(
            comentario.texto.startswith('[Simulación]')
            and comentario.estado == Comentario.Estado.PUBLICADO
            for comentario in Comentario.objects.all()
        ))
        self.assertEqual(ClicPublicacion.objects.count(), 4)

        self.ejecutar(aplicar=True)

        self.assertEqual(get_user_model().objects.filter(username__startswith='demo_sim_').count(), 5)
        self.assertEqual(ValoracionPublicacion.objects.count(), 3)
        self.assertEqual(Comentario.objects.count(), 2)
        self.assertEqual(ClicPublicacion.objects.count(), 4)

    @override_settings(DEBUG=False)
    def test_aplicar_rechaza_entorno_no_debug(self):
        with self.assertRaises(CommandError):
            self.ejecutar(aplicar=True)
        self.assertEqual(get_user_model().objects.filter(username__startswith='demo_sim_').count(), 0)
        self.assertFalse(ValoracionPublicacion.objects.exists())
