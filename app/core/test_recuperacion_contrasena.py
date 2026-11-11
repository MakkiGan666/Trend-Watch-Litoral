import re
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class RecuperacionContrasenaTests(TestCase):
    password_actual = 'Actual-Segura!92Litoral'
    password_nueva = 'Nueva-Segura!84Litoral'

    def setUp(self):
        self.usuario = get_user_model().objects.create_user(
            username='lector_reset', email='lector@example.test', password=self.password_actual,
        )
        self.solicitud_url = reverse('password_reset')

    def solicitar(self, email):
        return self.client.post(self.solicitud_url, {'email': email})

    def obtener_enlace(self):
        self.solicitar(self.usuario.email)
        self.assertEqual(len(mail.outbox), 1)
        enlace = re.search(r'http://[^\s]+', mail.outbox[0].body).group(0)
        return urlsplit(enlace).path

    def preparar_confirmacion(self, enlace):
        respuesta = self.client.get(enlace, follow=True)
        return respuesta, respuesta.request['PATH_INFO']

    def test_solicitud_existente_envia_enlace_y_usa_respuesta_generica(self):
        respuesta = self.solicitar(self.usuario.email)
        self.assertRedirects(respuesta, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('lector@example.test', mail.outbox[0].to)
        self.assertIn('/cuenta/restablecer/', mail.outbox[0].body)
        self.assertNotIn(self.password_actual, mail.outbox[0].body)
        confirmacion = self.client.get(respuesta.url)
        self.assertContains(confirmacion, 'Si existe una cuenta activa')

    def test_email_inexistente_no_enumera_cuenta(self):
        existente = self.solicitar(self.usuario.email)
        self.client.get(existente.url)
        mail.outbox.clear()
        desconocido = self.solicitar('desconocido@example.test')
        self.assertEqual(desconocido.status_code, existente.status_code)
        self.assertEqual(desconocido.url, existente.url)
        self.assertContains(self.client.get(desconocido.url), 'Si existe una cuenta activa')
        self.assertEqual(mail.outbox, [])

    def test_cuenta_sin_email_y_emails_activos_duplicados_no_reciben_enlace(self):
        get_user_model().objects.create_user(username='sin_email', email='', password=self.password_actual)
        respuesta_sin_email = self.solicitar('sinempleado@example.test')
        self.assertRedirects(respuesta_sin_email, reverse('password_reset_done'))
        self.assertEqual(mail.outbox, [])

        get_user_model().objects.create_user(
            username='duplicado', email=self.usuario.email.upper(), password=self.password_actual,
        )
        respuesta_duplicada = self.solicitar(self.usuario.email)
        self.assertRedirects(respuesta_duplicada, reverse('password_reset_done'))
        self.assertEqual(mail.outbox, [])

    def test_token_valido_cambia_password_y_se_invalida(self):
        enlace = self.obtener_enlace()
        formulario, enlace_confirmacion = self.preparar_confirmacion(enlace)
        self.assertContains(formulario, 'Elegí una nueva contraseña')
        respuesta = self.client.post(enlace_confirmacion, {
            'new_password1': self.password_nueva,
            'new_password2': self.password_nueva,
        })
        self.assertRedirects(respuesta, reverse('password_reset_complete'))
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password(self.password_nueva))
        self.assertFalse(self.usuario.check_password(self.password_actual))
        self.assertContains(self.client.get(enlace), 'El enlace ya no es válido')

    def test_token_invalido_vencido_y_reutilizado_son_rechazados(self):
        enlace = self.obtener_enlace()
        self.assertEqual(self.client.get(enlace.replace(enlace.rsplit('/', 2)[-2], 'token-invalido')).status_code, 200)
        with patch.object(
            PasswordResetTokenGenerator, '_now',
            return_value=datetime.now() + timedelta(days=4),
        ):
            vencido = self.client.get(enlace)
        self.assertContains(vencido, 'El enlace ya no es válido')
        _, enlace_confirmacion = self.preparar_confirmacion(enlace)
        respuesta = self.client.post(enlace_confirmacion, {
            'new_password1': self.password_nueva,
            'new_password2': self.password_nueva,
        })
        self.assertRedirects(respuesta, reverse('password_reset_complete'))
        self.assertContains(self.client.get(enlace), 'El enlace ya no es válido')

    def test_validador_rechaza_password_debil_y_acepta_una_valida(self):
        enlace = self.obtener_enlace()
        formulario, enlace_confirmacion = self.preparar_confirmacion(enlace)
        self.assertContains(formulario, 'Elegí una nueva contraseña')
        respuesta = self.client.post(enlace_confirmacion, {
            'new_password1': 'password', 'new_password2': 'password',
        })
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('new_password2', respuesta.context['form'].errors)
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password(self.password_actual))

        respuesta_valida = self.client.post(enlace_confirmacion, {
            'new_password1': self.password_nueva,
            'new_password2': self.password_nueva,
        })
        self.assertRedirects(respuesta_valida, reverse('password_reset_complete'))

    def test_password_nueva_permita_login_por_username_y_email(self):
        enlace = self.obtener_enlace()
        _, enlace_confirmacion = self.preparar_confirmacion(enlace)
        self.client.post(enlace_confirmacion, {
            'new_password1': self.password_nueva,
            'new_password2': self.password_nueva,
        })
        for identificador in ('lector_reset', self.usuario.email):
            self.client.logout()
            respuesta = self.client.post(reverse('login'), {
                'username': identificador, 'password': self.password_nueva,
            })
            self.assertRedirects(respuesta, '/')
            self.assertEqual(int(self.client.session['_auth_user_id']), self.usuario.pk)

    def test_csrf_en_solicitud_y_confirmacion(self):
        cliente_csrf = Client(enforce_csrf_checks=True)
        formulario = cliente_csrf.get(self.solicitud_url)
        token_csrf = formulario.cookies['csrftoken'].value
        datos = {'email': self.usuario.email}
        self.assertEqual(cliente_csrf.post(self.solicitud_url, datos).status_code, 403)
        respuesta = cliente_csrf.post(
            self.solicitud_url, datos, HTTP_X_CSRFTOKEN=token_csrf,
        )
        self.assertRedirects(respuesta, reverse('password_reset_done'))

        mail.outbox.clear()
        enlace = self.obtener_enlace()
        cliente_confirmacion = Client(enforce_csrf_checks=True)
        formulario_confirmacion = cliente_confirmacion.get(enlace, follow=True)
        self.assertContains(formulario_confirmacion, 'Elegí una nueva contraseña')
        enlace_confirmacion = formulario_confirmacion.request['PATH_INFO']
        self.assertEqual(cliente_confirmacion.post(enlace_confirmacion, {
            'new_password1': self.password_nueva,
            'new_password2': self.password_nueva,
        }).status_code, 403)

    def test_rutas_y_templates_del_recorrido(self):
        self.assertContains(self.client.get(self.solicitud_url), 'Recuperar contraseña')
        self.assertContains(self.client.get(reverse('password_reset_done')), 'Revisá tu correo')
        self.assertContains(self.client.get(reverse('password_reset_complete')), 'Contraseña actualizada')
