"""Identidades nuevas e históricas: sin HTTP externo, SDKs ni datos reales."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import connection, connections, transaction
from django.db.models import Q
from django.forms.models import model_to_dict
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import PerfilUsuario
from core.services.autenticacion import autenticar_identificador
from core.services.identidad import errores_identidad, serializar_identidad


PASSWORD = 'test-identity-only-583'


def datos_perfil(usuario, email=None):
    return {'accion': 'datos', 'datos-first_name': 'Ana', 'datos-last_name': '',
            'datos-email': email or usuario.email, 'datos-confirmar_password': PASSWORD,
            'datos-fecha_nacimiento': '', 'datos-celular': ''}


class IdentidadEntradasTests(TestCase):
    def setUp(self):
        self.modelo = get_user_model()
        self.usuario = self.modelo.objects.create_user('lector', email='lector@example.com', password=PASSWORD)

    def crear(self, username, email='', **extra):
        return self.modelo.objects.create_user(username, email=email, password=PASSWORD, **extra)

    def test_perfil_rechaza_username_ajeno_case_espacios_e_inactivos(self):
        for indice, activo in enumerate((True, False)):
            alias = f'Alias{indice}@example.com'
            self.crear(alias, f'otro{indice}@example.com', is_active=activo)
            self.client.force_login(self.usuario)
            respuesta = self.client.post(reverse('perfil'), datos_perfil(self.usuario, '  ' + alias.upper() + '  '))
            self.assertEqual(respuesta.status_code, 400)
            self.assertIn('email', respuesta.context['datos_form'].errors)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.email, 'lector@example.com')
        self.assertFalse(PerfilUsuario.objects.exists())

    def test_registro_rechaza_los_dos_sentidos_del_cruce(self):
        for indice, activo in enumerate((True, False)):
            owner = self.crear(f'Alias{indice}@example.com', f'correo{indice}@example.com', is_active=activo)
            for username, email in ((f'nuevo{indice}', ' ' + owner.username.upper() + ' '),
                                    (' ' + owner.email.upper() + ' ', f'nuevo{indice}@example.com')):
                with self.subTest(username=username, email=email):
                    respuesta = self.client.post(reverse('registro'), {'username': username, 'email': email, 'password': PASSWORD})
                    self.assertEqual(respuesta.status_code, 400)
                    self.assertFalse(respuesta.json()['success'])
        self.assertEqual(self.modelo.objects.count(), 3)

    def test_registro_comprueba_username_despues_de_nfkc(self):
        self.crear('propietario', 'alias@example.com')
        respuesta = self.client.post(reverse('registro'), {
            'username': 'ａｌｉａｓ＠ｅｘａｍｐｌｅ．ｃｏｍ', 'email': 'libre@example.com', 'password': PASSWORD})
        self.assertEqual(respuesta.status_code, 400)
        self.assertFalse(self.modelo.objects.filter(username='alias@example.com').exists())

    def test_username_y_email_de_la_misma_cuenta_siguen_permitidos(self):
        respuesta = self.client.post(reverse('registro'), {
            'username': 'nueva@example.com', 'email': 'NUEVA@example.com', 'password': PASSWORD})
        self.assertEqual(respuesta.status_code, 200)
        nueva = self.modelo.objects.get(username='nueva@example.com')
        self.assertEqual(int(self.client.session['_auth_user_id']), nueva.pk)
        propia = self.crear('propia@example.com', 'anterior@example.com')
        self.client.force_login(propia)
        respuesta = self.client.post(reverse('perfil'), datos_perfil(propia, propia.username))
        self.assertEqual(respuesta.status_code, 302)
        propia.refresh_from_db()
        self.assertEqual(propia.email, propia.username)

    def test_ambiguas_historicas_no_inician_sesion_ni_emiten_jwt(self):
        alias = self.crear('Alias@example.com', 'libre@example.com')
        otra = self.crear('otra', alias.username)
        antes = list(self.modelo.objects.order_by('pk').values('pk', 'username', 'email', 'password'))
        for activa in (True, False):
            otra.is_active = activa
            otra.save(update_fields=['is_active'])
            for identificador in (alias.username, '  ' + alias.username + '  '):
                with self.subTest(activa=activa, identificador=identificador), patch(
                    'core.serializers.LoginTokenObtainPairSerializer.get_token'
                ) as emitir:
                    datos = {'username': identificador, 'password': PASSWORD}
                    respuesta = self.client.post(reverse('login'), datos, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
                    self.assertEqual(respuesta.status_code, 400)
                    self.assertNotIn('_auth_user_id', self.client.session)
                    jwt = APIClient().post(reverse('token_obtain_pair'), datos, format='json')
                    self.assertEqual(jwt.status_code, 401)
                    self.assertNotIn('access', jwt.data)
                    emitir.assert_not_called()
        self.assertEqual(list(self.modelo.objects.order_by('pk').values('pk', 'username', 'email', 'password')), antes)

    def test_username_case_sensitive_no_autentica_como_otra_cuenta(self):
        self.crear('Alias@example.com', 'alias-libre@example.com')
        otra = self.crear('otra', 'alias@example.com')
        otra.set_password('test-second-identity-672')
        otra.save(update_fields=['password'])
        self.assertIsNone(autenticar_identificador(None, 'alias@example.com', PASSWORD))
        datos = {'username': 'alias@example.com', 'password': 'test-second-identity-672'}
        respuesta = self.client.post(reverse('login'), datos, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(int(self.client.session['_auth_user_id']), otra.pk)
        api = APIClient()
        token = api.post(reverse('token_obtain_pair'), datos, format='json')
        self.assertEqual(token.status_code, 200)
        api.credentials(HTTP_AUTHORIZATION='Bearer ' + token.data['access'])
        self.assertEqual(api.get(reverse('user_me')).data['id'], otra.pk)

    def test_edicion_ajena_a_identidad_no_reescribe_colision_historica(self):
        self.crear(self.usuario.email, 'propietario@example.com')
        antes = list(self.modelo.objects.order_by('pk').values('pk', 'username', 'email', 'password', 'is_staff'))
        self.client.force_login(self.usuario)
        respuesta = self.client.post(reverse('perfil'), datos_perfil(self.usuario))
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(list(self.modelo.objects.order_by('pk').values('pk', 'username', 'email', 'password', 'is_staff')), antes)
        self.assertIsNone(autenticar_identificador(None, self.usuario.email, PASSWORD))

    def test_espacios_de_entrada_se_recortan_sin_normalizar_historicos(self):
        historica = self.crear('  raro@example.com  ', 'historico@example.com')
        respuesta = self.client.post(reverse('registro'), {
            'username': '  normal  ', 'email': '  normal@example.com  ', 'password': PASSWORD})
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(self.modelo.objects.filter(username='normal', email='normal@example.com').exists())
        historica.refresh_from_db()
        self.assertEqual(historica.username, '  raro@example.com  ')
        self.assertIsNone(autenticar_identificador(None, historica.username, PASSWORD))
        self.assertEqual(autenticar_identificador(None, historica.email, PASSWORD).pk, historica.pk)

    def test_formularios_admin_validan_alta_username_y_edicion_email(self):
        from core.admin import UsuarioAltaForm, UsuarioCambioForm
        owner = self.crear('Alias@example.com', 'correo@example.com', is_active=False)
        alta = UsuarioAltaForm(data={'username': owner.email.upper(), 'usable_password': 'true',
                                    'password1': PASSWORD, 'password2': PASSWORD})
        self.assertFalse(alta.is_valid())
        self.assertIn('username', alta.errors)
        data = model_to_dict(self.usuario)
        data['email'] = owner.username.upper()
        cambio = UsuarioCambioForm(data=data, instance=self.usuario)
        self.assertFalse(cambio.is_valid())
        self.assertIn('email', cambio.errors)

    def test_admin_permite_datos_no_identitarios_de_historico_sin_repararlo(self):
        from core.admin import UsuarioCambioForm
        self.crear(self.usuario.email, 'propietario@example.com')
        data = model_to_dict(self.usuario)
        data['first_name'] = 'Nombre actualizado'
        form = UsuarioCambioForm(data=data, instance=self.usuario)
        self.assertTrue(form.is_valid(), form.errors)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.email, 'lector@example.com')

    def test_admin_post_y_permisos_y_csrf_siguen_vigentes(self):
        owner = self.crear('Alias@example.com', 'owner@example.com')
        administrador = self.modelo.objects.create_superuser('admin-identidad', password=PASSWORD)
        self.client.force_login(administrador)
        ruta = reverse('admin:auth_user_change', args=[self.usuario.pk])
        fecha = timezone.localtime(self.usuario.date_joined)
        data = {'username': self.usuario.username, 'email': owner.username, 'is_active': 'on',
                'first_name': '', 'last_name': '', 'date_joined_0': fecha.strftime('%Y-%m-%d'),
                'date_joined_1': fecha.strftime('%H:%M:%S'), 'last_login_0': '', 'last_login_1': '', '_save': 'Guardar'}
        respuesta = self.client.post(ruta, data)
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('email', respuesta.context['adminform'].form.errors)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.email, 'lector@example.com')
        staff = self.crear('staff-sin-permisos', is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.post(ruta, data).status_code, 403)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(administrador)
        self.assertEqual(csrf.post(ruta, data).status_code, 403)
        self.assertEqual(admin.site._registry[self.modelo].has_change_permission(
            type('Request', (), {'user': staff})()), False)

    def test_email_duplicado_con_case_e_inactivo_sigue_rechazado(self):
        self.crear('otra', 'duplicado@example.com', is_active=False)
        self.client.force_login(self.usuario)
        respuesta = self.client.post(reverse('perfil'), datos_perfil(self.usuario, ' DUPLICADO@example.com '))
        self.assertEqual(respuesta.status_code, 400)
        registro = self.client.post(reverse('registro'), {
            'username': 'nuevo', 'email': ' DUPLICADO@example.com ', 'password': PASSWORD})
        self.assertEqual(registro.status_code, 400)

    def test_admin_password_conserva_flujo_e_identidad_historica(self):
        self.crear(self.usuario.email, 'owner@example.com')
        administrador = self.modelo.objects.create_superuser('admin-password-identidad', password=PASSWORD)
        self.client.force_login(administrador)
        respuesta = self.client.post(reverse('admin:auth_user_password_change', args=[self.usuario.pk]), {
            'password1': 'test-admin-identity-final-583', 'password2': 'test-admin-identity-final-583',
            'usable_password': 'true',
        })
        self.assertEqual(respuesta.status_code, 302)
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password('test-admin-identity-final-583'))
        self.assertEqual((self.usuario.username, self.usuario.email), ('lector', 'lector@example.com'))
        self.assertEqual(self.client.get(reverse('admin:index')).status_code, 200)


class IdentidadConcurrentePostgreSQLTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != 'postgresql':
            self.skipTest('Requiere advisory locks y commits PostgreSQL independientes')
        self.usuario = get_user_model().objects.create_user('lector', email='lector@example.com', password=PASSWORD)

    @staticmethod
    def solicitar(ruta, data, usuario_pk=None):
        conexion = connections['default']
        try:
            with conexion.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
                cursor.execute("SET statement_timeout = '10s'")
            cliente = Client()
            if usuario_pk is not None:
                cliente.force_login(get_user_model().objects.get(pk=usuario_pk))
            return cliente.post(ruta, data).status_code
        finally:
            conexion.close()

    def ejecutar_carrera(self, tareas):
        barrera = Barrier(2)

        @contextmanager
        def juntos():
            barrera.wait(timeout=5)
            with serializar_identidad():
                yield

        with patch('core.services.identidad.serializar_identidad', juntos), patch(
            'core.views_perfil.serializar_identidad', juntos
        ), ThreadPoolExecutor(max_workers=2) as worker:
            futuros = [worker.submit(self.solicitar, *tarea) for tarea in tareas]
            return [f.result(timeout=20) for f in futuros]

    def test_dos_registros_cruzados_solo_confirman_una_cuenta(self):
        ruta = reverse('registro')
        resultados = self.ejecutar_carrera([
            (ruta, {'username': 'Alias@example.com', 'email': 'a@example.com', 'password': PASSWORD}),
            (ruta, {'username': 'otra', 'email': 'ALIAS@example.com', 'password': PASSWORD}),
        ])
        self.assertEqual(sorted(resultados), [200, 400])
        self.assertEqual(get_user_model().objects.filter(
            Q(username__iexact='alias@example.com') | Q(email__iexact='alias@example.com')).count(), 1)

    def test_perfil_y_alta_serializan_el_mismo_identificador(self):
        resultados = self.ejecutar_carrera([
            (reverse('perfil'), datos_perfil(self.usuario, 'Alias@example.com'), self.usuario.pk),
            (reverse('registro'), {'username': 'ALIAS@example.com', 'email': 'nueva@example.com', 'password': PASSWORD}),
        ])
        self.assertIn(resultados, ([302, 400], [400, 200]))
        self.assertEqual(get_user_model().objects.filter(
            Q(username__iexact='alias@example.com') | Q(email__iexact='alias@example.com')).count(), 1)

    def test_orm_ajeno_al_protocolo_puede_colisionar_pero_login_rechaza(self):
        otra = get_user_model().objects.create_user('otra', email='otra@example.com', password=PASSWORD)
        barrera = Barrier(2)

        def escribir(pk):
            conexion = connections['default']
            try:
                with transaction.atomic():
                    with conexion.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '5s'")
                        cursor.execute("SET LOCAL statement_timeout = '10s'")
                    usuario = get_user_model().objects.select_for_update().get(pk=pk)
                    self.assertEqual(errores_identidad(email='compartido@example.com', excluir_pk=pk), {})
                    barrera.wait(timeout=5)
                    usuario.email = 'compartido@example.com'
                    usuario.save(update_fields=['email'])
            finally:
                conexion.close()

        with ThreadPoolExecutor(max_workers=2) as worker:
            futuros = [worker.submit(escribir, pk) for pk in (self.usuario.pk, otra.pk)]
            for futuro in futuros:
                futuro.result(timeout=20)
        self.assertEqual(get_user_model().objects.filter(email='compartido@example.com').count(), 2)
        self.assertIsNone(autenticar_identificador(None, 'compartido@example.com', PASSWORD))
        self.assertEqual(APIClient().post(reverse('token_obtain_pair'), {
            'username': 'compartido@example.com', 'password': PASSWORD}, format='json').status_code, 401)
