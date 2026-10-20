from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import PerfilUsuario, Publicacion, PublicacionGuardada


class PerfilTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user('lector_perfil', email='lector@example.com', password='test-profile-original')
        cls.otro = get_user_model().objects.create_user('otro_perfil', email='otro@example.com', password='test-profile-other')
        cls.noticia = Publicacion.objects.create(hash_origen='perfil-prueba', titulo='Noticia guardable', contenido='Contenido')

    def test_acceso_privado_y_perfil_sin_crear_datos_en_get(self):
        self.assertEqual(self.client.get(reverse('perfil')).status_code, 302)
        self.client.force_login(self.usuario)
        response = self.client.get(reverse('perfil'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Mis guardados')
        self.assertContains(response, 'lector@example.com')
        self.assertFalse(PerfilUsuario.objects.exists())
        self.assertFalse(self.usuario.is_staff)

    def enviar_datos(self, **extra):
        data = {'accion': 'datos', 'datos-first_name': 'Ana', 'datos-last_name': 'Prueba',
                'datos-email': self.usuario.email, 'datos-fecha_nacimiento': '2000-03-04',
                'datos-celular': '+54 376 1234567'}
        return self.client.post(reverse('perfil'), {**data, **extra})

    def test_editar_solo_datos_propios_sin_permisos_inyectados(self):
        self.client.force_login(self.usuario)
        self.assertEqual(self.enviar_datos(usuario=self.otro.pk, is_superuser='true').status_code, 302)
        self.usuario.refresh_from_db()
        self.otro.refresh_from_db()
        self.assertEqual(self.usuario.first_name, 'Ana')
        self.assertFalse(self.usuario.is_superuser)
        self.assertEqual(self.otro.first_name, '')
        self.assertEqual(self.usuario.perfil.fecha_nacimiento, date(2000, 3, 4))

    def test_email_exige_password_y_no_admite_duplicado(self):
        self.client.force_login(self.usuario)
        self.assertEqual(self.enviar_datos(**{'datos-email': 'nuevo@example.com'}).status_code, 400)
        self.assertEqual(self.enviar_datos(**{'datos-email': 'OTRO@example.com', 'datos-confirmar_password': 'test-profile-original'}).status_code, 400)
        self.assertEqual(self.enviar_datos(**{'datos-email': 'nuevo@example.com', 'datos-confirmar_password': 'test-profile-original'}).status_code, 302)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.email, 'nuevo@example.com')

    def test_rechaza_fecha_futura_y_celular_invalido(self):
        self.client.force_login(self.usuario)
        response = self.enviar_datos(**{'datos-fecha_nacimiento': (timezone.localdate() + timedelta(days=1)).isoformat(), 'datos-celular': '<script>'})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(PerfilUsuario.objects.exists())

    def test_password_actual_obligatoria_y_sesion_conservada(self):
        self.client.force_login(self.usuario)
        data = {'accion': 'password', 'password-old_password': 'incorrecta',
                'password-new_password1': 'changed-profile-password-895',
                'password-new_password2': 'changed-profile-password-895'}
        self.assertEqual(self.client.post(reverse('perfil'), data).status_code, 400)
        data['password-old_password'] = 'test-profile-original'
        self.assertEqual(self.client.post(reverse('perfil'), data).status_code, 302)
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password(data['password-new_password1']))
        self.assertEqual(self.client.get(reverse('perfil')).status_code, 200)

    def test_guardados_idempotentes_privados_y_retiro_solo_propio(self):
        self.client.force_login(self.usuario)
        url = reverse('guardar_publicacion', args=[self.noticia.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        for _ in range(2):
            self.assertEqual(self.client.post(url, {'accion': 'guardar', 'usuario': self.otro.pk}).status_code, 302)
        self.assertEqual(PublicacionGuardada.objects.count(), 1)
        self.assertContains(self.client.get(reverse('mis_guardados')), self.noticia.titulo)
        self.client.force_login(self.otro)
        self.assertNotContains(self.client.get(reverse('mis_guardados')), self.noticia.titulo)
        self.client.post(url, {'accion': 'quitar'})
        self.assertEqual(PublicacionGuardada.objects.count(), 1)
        self.client.force_login(self.usuario)
        self.client.post(url, {'accion': 'quitar'})
        self.assertFalse(PublicacionGuardada.objects.exists())

    def test_csrf_en_cambios_y_guardados(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.usuario)
        self.assertEqual(client.post(reverse('perfil'), {'accion': 'datos'}).status_code, 403)
        self.assertEqual(client.post(reverse('guardar_publicacion', args=[self.noticia.pk]), {'accion': 'guardar'}).status_code, 403)

    def test_notificaciones_reutiliza_preferencia_y_cuenta_enlaza_perfil(self):
        self.client.force_login(self.usuario)
        response = self.client.get(reverse('perfil_notificaciones'))
        self.assertContains(response, 'data-notification-configure')
        self.assertContains(response, 'href="/perfil/"')
