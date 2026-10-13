from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse


class ModalAuthenticationViewsTests(TestCase):
    password = 'M4r!posas_Rio#83'

    def setUp(self):
        self.login_url = reverse('login')
        self.register_url = reverse('registro')
        self.user_model = get_user_model()

    def test_registration_creates_user_with_hashed_password_and_logs_in(self):
        response = self.client.post(self.register_url, {
            'username': 'sofialitoral',
            'email': 'sofia@example.com',
            'password': self.password,
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'success': True,
            'message': 'Cuenta creada correctamente.',
            'username': 'sofialitoral',
        })
        user = self.user_model.objects.get(username='sofialitoral')
        self.assertTrue(user.check_password(self.password))
        self.assertIn('_auth_user_id', self.client.session)

        self.client.logout()
        login_response = self.client.post(self.login_url, {
            'username': user.email,
            'password': self.password,
        })
        self.assertRedirects(login_response, '/')
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

    def test_registration_rejects_missing_fields_and_duplicate_username_or_email(self):
        missing = self.client.post(self.register_url, {
            'username': '',
            'email': 'sofia@example.com',
            'password': self.password,
        })
        self.assertEqual(missing.status_code, 400)

        self.user_model.objects.create_user(
            username='yaexiste',
            email='existente@example.com',
            password=self.password,
        )
        duplicate_username = self.client.post(self.register_url, {
            'username': 'yaexiste',
            'email': 'nuevo@example.com',
            'password': self.password,
        })
        duplicate_email = self.client.post(self.register_url, {
            'username': 'otro',
            'email': 'EXISTENTE@example.com',
            'password': self.password,
        })
        self.assertEqual(duplicate_username.status_code, 400)
        self.assertIn('nombre de usuario', duplicate_username.json()['message'])
        self.assertEqual(duplicate_email.status_code, 400)
        self.assertIn('email', duplicate_email.json()['message'])

        invalid_email = self.client.post(self.register_url, {
            'username': 'nuevo',
            'email': 'no-es-un-email',
            'password': self.password,
        })
        weak_password = self.client.post(self.register_url, {
            'username': 'nuevousuario',
            'email': 'nuevo@example.com',
            'password': 'password',
        })
        self.assertEqual(invalid_email.status_code, 400)
        self.assertEqual(weak_password.status_code, 400)

    def test_login_accepts_username_or_email_and_returns_json(self):
        self.user_model.objects.create_user(
            username='sofialitoral',
            email='sofia@example.com',
            password=self.password,
        )

        for identifier in ('sofialitoral', 'sofia@example.com'):
            self.client.logout()
            response = self.client.post(self.login_url, {
                'username': identifier,
                'password': self.password,
            }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {
                'success': True,
                'username': 'sofialitoral',
            })

    def test_login_rejects_invalid_credentials_with_json_error(self):
        response = self.client.post(self.login_url, {
            'username': 'inexistente',
            'password': 'incorrecta',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])
        self.assertIn('incorrectos', response.json()['message'])

    def test_landing_shows_modal_and_switches_nav_for_authenticated_user(self):
        response = self.client.get('/')
        self.assertContains(response, 'id="login-modal"')
        self.assertContains(response, '¿Todavía no tenés cuenta?')
        self.assertContains(response, '¿Ya tenés una cuenta?')
        self.assertContains(response, 'Ingresar')

        user = self.user_model.objects.create_user(
            username='sofialitoral',
            password=self.password,
        )
        self.client.force_login(user)
        authenticated_response = self.client.get('/')

        self.assertContains(authenticated_response, 'Hola, sofialitoral')
        self.assertContains(authenticated_response, 'Cerrar sesión')
        self.assertNotContains(authenticated_response, '<span>Ingresar</span>', html=True)

    def test_logout_ends_session_and_returns_to_safe_requested_page(self):
        user = self.user_model.objects.create_user(
            username='sofialitoral',
            password=self.password,
        )
        self.client.force_login(user)

        response = self.client.post(reverse('logout'), {'next': '/categorias/'})

        self.assertRedirects(response, '/categorias/', fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_csrf_is_required_for_authentication_posts(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.get('/')
        csrf_token = csrf_client.cookies['csrftoken'].value
        data = {
            'username': 'sofialitoral',
            'email': 'sofia@example.com',
            'password': self.password,
        }

        rejected = csrf_client.post(self.register_url, data)
        accepted = csrf_client.post(
            self.register_url,
            data,
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(accepted.status_code, 200)
