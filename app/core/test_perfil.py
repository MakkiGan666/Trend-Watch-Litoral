from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, TransactionTestCase
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


    def con_cambio_concurrente(self, cambiar):
        """Intercalar otra instancia tras validar y antes del guardado real.

        No simula conexiones simultáneas: reproduce determinísticamente la
        instancia obsoleta con dos objetos ORM. No reemplaza User.save ni BD.
        """
        from unittest.mock import patch
        from .forms_perfil import PerfilForm
        guardar_original = PerfilForm.save

        def guardar(form, *args, **kwargs):
            segunda = get_user_model().objects.get(pk=form.instance.pk)
            self.assertIsNot(segunda, form.instance)
            cambiar(segunda)
            return guardar_original(form, *args, **kwargs)

        return patch.object(PerfilForm, 'save', autospec=True, side_effect=guardar)

    def test_aud01_password_concurrente_no_se_revierte_ni_revalida_sesion_vieja(self):
        from django.contrib.auth import authenticate
        self.client.force_login(self.usuario)
        nuevo_hash = []

        def cambiar(segunda):
            segunda.set_password('test-profile-concurrent-new-642')
            segunda.save(update_fields=['password'])
            nuevo_hash.append(segunda.password)

        with self.con_cambio_concurrente(cambiar):
            respuesta = self.enviar_datos()
        self.assertEqual(respuesta.status_code, 302)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.password, nuevo_hash[0])
        self.assertEqual(self.usuario.first_name, 'Ana')
        self.assertIsNotNone(authenticate(username=self.usuario.username, password='test-profile-concurrent-new-642'))
        self.assertIsNone(authenticate(username=self.usuario.username, password='test-profile-original'))
        self.assertEqual(self.client.get(reverse('perfil')).status_code, 302)
        self.otro.refresh_from_db()
        self.assertTrue(self.otro.check_password('test-profile-other'))

    def test_aud01_atributos_protegidos_concurrentes_no_se_revierten(self):
        self.client.force_login(self.usuario)
        instante = timezone.now() - timedelta(days=2)

        def cambiar(segunda):
            segunda.username = 'lector_renombrado'
            segunda.is_staff = True
            segunda.is_superuser = True
            segunda.is_active = False
            segunda.last_login = instante
            segunda.date_joined = instante
            segunda.save(update_fields=['username', 'is_staff', 'is_superuser', 'is_active',
                                        'last_login', 'date_joined'])

        with self.con_cambio_concurrente(cambiar):
            self.assertEqual(self.enviar_datos().status_code, 302)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.username, 'lector_renombrado')
        self.assertTrue(self.usuario.is_staff)
        self.assertTrue(self.usuario.is_superuser)
        self.assertFalse(self.usuario.is_active)
        self.assertEqual(self.usuario.last_login, instante)
        self.assertEqual(self.usuario.date_joined, instante)
        self.assertEqual(self.usuario.first_name, 'Ana')

    def test_aud01_nombre_editado_no_reescribe_email_y_apellido_no_editados(self):
        self.client.force_login(self.usuario)

        def cambiar(segunda):
            segunda.email = 'concurrente@example.com'
            segunda.last_name = 'Concurrente'
            segunda.save(update_fields=['email', 'last_name'])

        with self.con_cambio_concurrente(cambiar):
            respuesta = self.enviar_datos(**{'datos-last_name': self.usuario.last_name})
        self.assertEqual(respuesta.status_code, 302)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.first_name, 'Ana')
        self.assertEqual(self.usuario.last_name, 'Concurrente')
        self.assertEqual(self.usuario.email, 'concurrente@example.com')

    def test_aud01_fecha_y_celular_no_emiten_update_de_usuario(self):
        from unittest.mock import patch
        self.client.force_login(self.usuario)
        modelo = get_user_model()
        # El guardado de sesión de force_login queda fuera del control.
        with patch.object(modelo, 'save', autospec=True, side_effect=modelo.save) as guardar:
            respuesta = self.enviar_datos(**{'datos-first_name': self.usuario.first_name,
                                             'datos-last_name': self.usuario.last_name})
        self.assertEqual(respuesta.status_code, 302)
        guardar.assert_not_called()
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.perfil.fecha_nacimiento, date(2000, 3, 4))
        self.assertEqual(self.usuario.perfil.celular, '+54 376 1234567')

    def test_aud01_fallo_del_perfil_revierte_update_de_usuario(self):
        from unittest.mock import patch
        self.client.force_login(self.usuario)
        with patch.object(PerfilUsuario.objects, 'update_or_create', side_effect=RuntimeError('fallo simulado')):
            with self.assertRaises(RuntimeError):
                self.enviar_datos()
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.first_name, '')
        self.assertEqual(self.usuario.last_name, '')
        self.assertEqual(self.usuario.email, 'lector@example.com')
        self.assertTrue(self.usuario.check_password('test-profile-original'))
        self.assertFalse(PerfilUsuario.objects.exists())


class PerfilCredencialesVigentesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user(
            'lector_vigente', email='vigente@example.com', password='test-profile-original')

    enviar_datos = PerfilTests.enviar_datos

    def rotacion_previa(self, activa=True):
        """Cambiar BD tras cargar request.user, antes de validar formulario bound."""
        from unittest.mock import patch
        from django.contrib.auth.forms import PasswordChangeForm
        self.hash_rotado = []

        def crear(user, *args, **kwargs):
            if not self.hash_rotado:
                segunda = get_user_model().objects.get(pk=user.pk)
                self.assertIsNot(segunda, user)
                segunda.set_password('test-profile-rotated-548')
                segunda.is_active = activa
                segunda.save(update_fields=['password', 'is_active'])
                self.hash_rotado.append(segunda.password)
                self.assertNotEqual(user.password, segunda.password)
            return PasswordChangeForm(user, *args, **kwargs)

        return patch('core.views_perfil.PasswordChangeForm', side_effect=crear)

    def enviar_email(self, clave):
        return self.enviar_datos(**{'datos-email': 'cambiado@example.com',
                                   'datos-confirmar_password': clave})

    def enviar_password(self, clave):
        return self.client.post(reverse('perfil'), {
            'accion': 'password', 'password-old_password': clave,
            'password-new_password1': 'test-profile-final-937',
            'password-new_password2': 'test-profile-final-937',
        })

    def test_email_rechaza_password_anterior_tras_rotacion(self):
        self.client.force_login(self.usuario)
        with self.rotacion_previa():
            respuesta = self.enviar_email('test-profile-original')
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('confirmar_password', respuesta.context['datos_form'].errors)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.email, 'vigente@example.com')
        self.assertEqual(self.usuario.password, self.hash_rotado[0])
        self.assertFalse(PerfilUsuario.objects.exists())

    def test_email_acepta_password_vigente_sin_renovar_sesion_obsoleta(self):
        self.client.force_login(self.usuario)
        with self.rotacion_previa():
            respuesta = self.enviar_email('test-profile-rotated-548')
        self.assertEqual(respuesta.status_code, 302)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.email, 'cambiado@example.com')
        self.assertEqual(self.usuario.password, self.hash_rotado[0])
        self.assertEqual(self.client.get(reverse('perfil')).status_code, 302)

    def test_cambio_password_rechaza_clave_anterior_tras_rotacion(self):
        self.client.force_login(self.usuario)
        with self.rotacion_previa():
            respuesta = self.enviar_password('test-profile-original')
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('old_password', respuesta.context['password_form'].errors)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.password, self.hash_rotado[0])

    def test_cambio_password_acepta_clave_vigente_y_conserva_sesion(self):
        self.client.force_login(self.usuario)
        with self.rotacion_previa():
            respuesta = self.enviar_password('test-profile-rotated-548')
        self.assertEqual(respuesta.status_code, 302)
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password('test-profile-final-937'))
        self.assertFalse(self.usuario.check_password('test-profile-original'))
        self.assertFalse(self.usuario.check_password('test-profile-rotated-548'))
        self.assertEqual(self.client.get(reverse('perfil')).status_code, 200)

    def test_fallo_posterior_a_guardar_password_revierte_la_operacion(self):
        from unittest.mock import patch
        self.client.force_login(self.usuario)
        with self.rotacion_previa(), patch('core.views_perfil.update_session_auth_hash',
                                          side_effect=RuntimeError('fallo simulado')):
            with self.assertRaises(RuntimeError):
                self.enviar_password('test-profile-rotated-548')
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.password, self.hash_rotado[0])

    def test_fallo_perfil_revierte_email_pero_conserva_rotacion_previa(self):
        from unittest.mock import patch
        self.client.force_login(self.usuario)
        with self.rotacion_previa(), patch.object(PerfilUsuario.objects, 'update_or_create',
                                                 side_effect=RuntimeError('fallo simulado')):
            with self.assertRaises(RuntimeError):
                self.enviar_email('test-profile-rotated-548')
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.email, 'vigente@example.com')
        self.assertEqual(self.usuario.password, self.hash_rotado[0])
        self.assertFalse(PerfilUsuario.objects.exists())

    def test_cuenta_desactivada_no_se_autoriza_con_request_obsoleto(self):
        self.client.force_login(self.usuario)
        with self.rotacion_previa(activa=False):
            respuesta = self.enviar_email('test-profile-rotated-548')
        self.assertEqual(respuesta.status_code, 403)
        self.usuario.refresh_from_db()
        self.assertFalse(self.usuario.is_active)
        self.assertEqual(self.usuario.email, 'vigente@example.com')


class PerfilBloqueoPostgreSQLTests(TransactionTestCase):
    """Dos conexiones reales, sin sleeps ni hilos que esperen indefinidamente."""
    def setUp(self):
        from django.db import connection
        if connection.vendor != 'postgresql':
            self.skipTest('Requiere PostgreSQL para verificar bloqueo y commit entre conexiones')
        self.usuario = get_user_model().objects.create_user(
            'lector_bloqueo', email='bloqueo@example.com', password='test-profile-original')

    @staticmethod
    def rotar_en_otra_conexion(pk, password_hash):
        from django.db import DatabaseError, connections, transaction
        conexion = connections['default']
        try:
            with transaction.atomic():
                with conexion.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '250ms'")
                    cursor.execute("SET LOCAL statement_timeout = '3s'")
                get_user_model().objects.filter(pk=pk).update(password=password_hash)
            return 'commit'
        except DatabaseError as error:
            causa = error.__cause__
            return getattr(causa, 'pgcode', None) or getattr(getattr(causa, 'diag', None), 'sqlstate', None)
        finally:
            conexion.close()

    def post_sensible(self, accion):
        if accion == 'datos':
            return self.client.post(reverse('perfil'), {
                'accion': 'datos', 'datos-first_name': 'Ana', 'datos-last_name': '',
                'datos-email': 'nuevo@example.com', 'datos-confirmar_password': 'test-profile-original',
                'datos-fecha_nacimiento': '', 'datos-celular': '',
            })
        return self.client.post(reverse('perfil'), {
            'accion': 'password', 'password-old_password': 'test-profile-original',
            'password-new_password1': 'test-profile-final-937',
            'password-new_password2': 'test-profile-final-937',
        })

    def test_rotacion_confirmada_antes_de_validar_rechaza_clave_anterior(self):
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch
        from django.contrib.auth.forms import PasswordChangeForm
        from django.contrib.auth.hashers import make_password
        for accion in ('datos', 'password'):
            with self.subTest(accion=accion), ThreadPoolExecutor(max_workers=1) as worker:
                self.usuario.set_password('test-profile-original')
                self.usuario.save(update_fields=['password'])
                self.client.force_login(self.usuario)
                nuevo_hash = make_password('test-profile-rotated-548')
                rotada = []

                def crear(user, *args, **kwargs):
                    if not rotada:
                        # El formulario sin bind recibe el request.user ya cargado.
                        resultado = worker.submit(self.rotar_en_otra_conexion, user.pk, nuevo_hash).result(timeout=5)
                        self.assertEqual(resultado, 'commit')
                        self.assertNotEqual(user.password, nuevo_hash)
                        rotada.append(True)
                    return PasswordChangeForm(user, *args, **kwargs)

                with patch('core.views_perfil.PasswordChangeForm', side_effect=crear):
                    respuesta = self.post_sensible(accion)
                self.assertEqual(respuesta.status_code, 400)
                self.usuario.refresh_from_db()
                self.assertEqual(self.usuario.password, nuevo_hash)
                self.assertEqual(self.usuario.email, 'bloqueo@example.com')

    def test_rotacion_no_puede_confirmarse_entre_validacion_y_escritura(self):
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch
        from django.contrib.auth.forms import PasswordChangeForm
        from django.contrib.auth.hashers import make_password
        from .forms_perfil import PerfilForm
        for accion, formulario in (('datos', PerfilForm), ('password', PasswordChangeForm)):
            with self.subTest(accion=accion), ThreadPoolExecutor(max_workers=1) as worker:
                self.usuario.set_password('test-profile-original')
                self.usuario.save(update_fields=['password'])
                self.client.force_login(self.usuario)
                validar_original = formulario.is_valid
                nuevo_hash = make_password('test-profile-rotated-548')
                intentos = []

                def validar(form):
                    # Una UPDATE real concurrente debe esperar a nuestro commit.
                    resultado = worker.submit(self.rotar_en_otra_conexion, self.usuario.pk, nuevo_hash).result(timeout=5)
                    intentos.append(resultado)
                    self.assertEqual(resultado, '55P03')  # lock_timeout, no un error arbitrario.
                    return validar_original(form)

                with patch.object(formulario, 'is_valid', autospec=True, side_effect=validar):
                    respuesta = self.post_sensible(accion)
                self.assertEqual(respuesta.status_code, 302)
                self.assertEqual(intentos, ['55P03'])
                # El bloqueo se libera al completar la operación, también para password.
                resultado = worker.submit(self.rotar_en_otra_conexion, self.usuario.pk, nuevo_hash).result(timeout=5)
                self.assertEqual(resultado, 'commit')
                self.usuario.refresh_from_db()
                self.assertEqual(self.usuario.password, nuevo_hash)
