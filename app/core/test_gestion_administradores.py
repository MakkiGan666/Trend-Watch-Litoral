import logging
from io import StringIO
from unittest.mock import patch

from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.db import IntegrityError
from django.test import Client, RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.roles import PERMISOS_ADMINISTRADOR

User = get_user_model()


class GestionAdministradoresTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('configurar_roles', stdout=StringIO())
        cls.admin = User.objects.create_user('juan', is_staff=True)
        cls.admin.groups.add(Group.objects.get(name='Administrador'))
        cls.normal = User.objects.create_user('lector')
        cls.root = User.objects.create_superuser('root')

    def setUp(self):
        self.url = reverse('gestion_administradores')
        self.datos = {'username': 'pepe', 'email': 'pepe@example.com',
                      'password1': 'Rio!Litoral-9xQ482', 'password2': 'Rio!Litoral-9xQ482'}

    def test_autorizacion_get_post(self):
        for usuario, esperado in ((None, 302), (self.normal, 403), (self.admin, 200), (self.root, 200)):
            self.client.logout()
            if usuario:
                self.client.force_login(usuario)
            self.assertEqual(self.client.get(self.url).status_code, esperado)
            if esperado != 200:
                self.assertEqual(self.client.post(self.url, self.datos).status_code, esperado)
        self.assertFalse(User.objects.filter(username='pepe').exists())

    @override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.PBKDF2PasswordHasher'])
    def test_creacion_permisos_hash_auditoria_y_tercer_administrador(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url, self.datos, follow=True)
        self.assertContains(response, 'Administrador creado correctamente')
        pepe = User.objects.get(username='pepe')
        self.assertTrue(pepe.check_password(self.datos['password1']))
        self.assertNotEqual(pepe.password, self.datos['password1'])
        self.assertTrue(pepe.password.startswith('pbkdf2_sha256$'))
        self.assertTrue(pepe.is_staff)
        self.assertFalse(pepe.is_superuser)
        self.assertEqual(pepe.get_all_permissions(), self.admin.get_all_permissions())
        self.assertEqual(pepe.get_all_permissions(), PERMISOS_ADMINISTRADOR)
        self.assertFalse(pepe.user_permissions.exists())
        self.assertEqual(list(pepe.groups.values_list('name', flat=True)), ['Administrador'])
        evento = LogEntry.objects.get(object_id=str(pepe.pk))
        self.assertEqual(evento.user_id, self.admin.pk)
        self.assertIsNotNone(evento.action_time)
        self.assertNotIn(self.datos['password1'], str(evento.__dict__))
        self.assertNotIn(pepe.password, str(evento.__dict__))
        self.assertNotContains(response, self.datos['password1'])
        for identificador in (pepe.username, pepe.email):
            self.client.get(reverse('logout'))
            self.assertEqual(self.client.post(reverse('login'), {
                'username': identificador, 'password': self.datos['password1'],
            }).status_code, 302)
            self.assertEqual(int(self.client.session['_auth_user_id']), pepe.pk)
        for vista in ('publicaciones', 'dashboard', 'gestion_administradores'):
            self.assertEqual(self.client.get(reverse(vista)).status_code, 200)
        self.assertEqual(self.client.get('/admin/').status_code, 200)
        self.datos.update(username='tercero', email='tercero@example.com')
        self.assertEqual(self.client.post(self.url, self.datos).status_code, 302)
        self.assertEqual(User.objects.get(username='tercero').get_all_permissions(), pepe.get_all_permissions())

    def test_formulario_invalido_no_crea_cuentas_ni_auditoria(self):
        self.client.force_login(self.admin)
        variantes = [
            {'username': 'JUAN'}, {'username': 'mal nombre'},
            {'email': 'invalido'}, {'email': 'a' * 255 + '@example.com'},
            {'password1': '123', 'password2': '123'},
            {'password2': 'diferente'},
            *[{campo: ''} for campo in self.datos],
        ]
        User.objects.create_user('existente', email='reservado@example.com')
        variantes.extend([{'email': 'RESERVADO@example.com'}, {'username': 'reservado@example.com'}])
        cantidad = User.objects.count()
        for cambio in variantes:
            with self.subTest(cambio=cambio):
                response = self.client.post(self.url, {**self.datos, **cambio})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['form'].errors)
                self.assertNotContains(response, self.datos['password1'])
                self.assertEqual(User.objects.count(), cantidad)
                self.assertEqual(LogEntry.objects.count(), 0)

    def test_privilegios_manipulados_se_ignoran(self):
        self.client.force_login(self.admin)
        self.client.post(self.url, {**self.datos, 'is_superuser': 'true', 'is_staff': '',
                                  'is_active': '', 'groups': Group.objects.get(name='Usuario').pk,
                                  'user_permissions': list(Permission.objects.values_list('pk', flat=True))})
        pepe = User.objects.get(username='pepe')
        self.assertFalse(pepe.is_superuser)
        self.assertTrue(pepe.is_staff)
        self.assertTrue(pepe.is_active)
        self.assertEqual(pepe.get_all_permissions(), PERMISOS_ADMINISTRADOR)

    def test_csrf_y_metodos(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(self.url, self.datos).status_code, 403)
        client.get(self.url)
        self.assertEqual(client.post(self.url, self.datos, HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value).status_code, 302)
        for metodo in ('put', 'patch', 'delete'):
            self.client.force_login(self.admin)
            self.assertEqual(getattr(self.client, metodo)(self.url).status_code, 405)

    def test_visibilidad_y_administrador_sin_superusuario(self):
        for usuario in (None, self.normal, self.admin, self.root):
            self.client.logout()
            if usuario:
                self.client.force_login(usuario)
            response = self.client.get(reverse('landing'))
            if usuario in (self.admin, self.root):
                self.assertContains(response, 'Gestión de administradores')
                self.assertContains(response, 'id="inicio-indicadores"')
                for vista in ('publicaciones', 'dashboard'):
                    self.assertContains(self.client.get(reverse(vista)), 'Gestión de administradores')
            else:
                self.assertNotContains(response, 'Gestión de administradores')

    def test_staff_sin_permisos_no_autoriza(self):
        self.normal.is_staff = True
        self.normal.save()
        self.client.force_login(self.normal)
        self.assertEqual(self.client.post(self.url, self.datos).status_code, 403)

    def test_grupo_incompleto_falla_sin_alta(self):
        self.client.force_login(self.root)
        Group.objects.get(name='Administrador').permissions.clear()
        response = self.client.post(self.url, self.datos)
        self.assertTrue(response.context['form'].non_field_errors())
        self.assertFalse(User.objects.filter(username='pepe').exists())

    def test_fallo_auditoria_revierte_alta_y_no_expone_secretos(self):
        self.client.force_login(self.admin)
        with patch('core.views_administradores.LogEntry.objects.log_actions', side_effect=IntegrityError('detalle interno')):
            response = self.client.post(self.url, self.datos)
        self.assertFalse(User.objects.filter(username='pepe').exists())
        self.assertNotContains(response, 'detalle interno')
        self.assertNotContains(response, self.datos['password1'])
        self.assertTrue(response.context['form'].non_field_errors())

    def test_registros_y_respuestas_no_contienen_secretos(self):
        self.client.force_login(self.admin)
        salida = StringIO()
        handler = logging.StreamHandler(salida)
        logger = logging.getLogger()
        logger.addHandler(handler)
        try:
            response = self.client.post(self.url, self.datos, follow=True)
            self.assertNotContains(response, self.datos['password1'])
            self.assertNotIn(self.datos['password1'], salida.getvalue())
            self.assertNotIn(User.objects.get(username='pepe').password, salida.getvalue())
        finally:
            logger.removeHandler(handler)

    def test_permisos_efectivos_iguales_entre_administradores_del_rol(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(self.url, self.datos).status_code, 302)
        nuevo = User.objects.get(username='pepe')
        factory = RequestFactory()
        for modelo, model_admin in admin.site._registry.items():
            permisos = []
            for usuario in (self.root, self.admin, nuevo):
                request = factory.get('/admin/')
                request.user = usuario
                permisos.append((model_admin.has_module_permission(request), model_admin.get_model_perms(request)))
            with self.subTest(modelo=modelo._meta.label):
                self.assertEqual(permisos[1], permisos[2])
                # Las operaciones de contenido conservan su alcance administrativo.
                # Los privilegios técnicos JWT permanecen exclusivos de superusuarios.
                if modelo._meta.app_label == 'core':
                    self.assertEqual(permisos[0], permisos[1])

    def test_tokens_jwt_reservados_a_superusuarios(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(self.url, self.datos).status_code, 302)
        nuevo = User.objects.get(username='pepe')
        for usuario in (self.admin, nuevo):
            self.client.force_login(usuario)
            self.assertFalse(usuario.has_module_perms('token_blacklist'))
            for modelo in ('outstandingtoken', 'blacklistedtoken'):
                for accion in ('view', 'add', 'change', 'delete'):
                    self.assertFalse(usuario.has_perm(f'token_blacklist.{accion}_{modelo}'))
                for vista in ('changelist', 'add'):
                    ruta = reverse(f'admin:token_blacklist_{modelo}_{vista}')
                    with self.subTest(usuario=usuario.username, modelo=modelo, vista=vista):
                        self.assertEqual(self.client.get(ruta).status_code, 403)
                        self.assertEqual(self.client.post(ruta, {}).status_code, 403)
        self.client.force_login(self.root)
        for modelo in ('outstandingtoken', 'blacklistedtoken'):
            self.assertEqual(self.client.get(reverse(f'admin:token_blacklist_{modelo}_changelist')).status_code, 200)


class SeguridadAdministrativaTests(TestCase):
    setUpTestData = classmethod(GestionAdministradoresTests.setUpTestData.__func__)
    setUp = GestionAdministradoresTests.setUp
    # Autorización HTTP y estado persistido, independientes de la interfaz.
    def test_permisos_sin_rol_no_autorizan(self):
        self.normal.is_staff = True
        self.normal.save()
        self.normal.user_permissions.set(Group.objects.get(name='Administrador').permissions.all())
        self.client.force_login(self.normal)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, self.datos).status_code, 403)
        self.assertFalse(User.objects.filter(username='pepe').exists())
        self.assertNotContains(self.client.get(reverse('landing')), 'Gestión de administradores')

    def test_escrituras_auth_reservadas_incluso_con_permisos_historicos(self):
        # Simular una instalación anterior y permisos directos accidentales.
        self.admin.user_permissions.set(Permission.objects.filter(content_type__app_label='auth'))
        tecnico = Group.objects.create(name='Tecnico')
        tecnico.permissions.set(Permission.objects.filter(content_type__app_label='token_blacklist'))
        grupo = Group.objects.get(name='Administrador')
        permisos = list(grupo.permissions.order_by('pk').values_list('pk', flat=True))
        self.client.force_login(self.admin)
        antes = list(User.objects.order_by('pk').values())
        relaciones = [(u.pk, set(u.groups.values_list('pk', flat=True)),
                       set(u.user_permissions.values_list('pk', flat=True))) for u in User.objects.all()]
        for usuario in (self.admin, self.normal, self.root):
            datos = {'username': usuario.username, 'email': 'alterado@example.com',
                     'is_active': 'on', 'is_staff': 'on', 'is_superuser': 'on',
                     'groups': [grupo.pk, tecnico.pk],
                     'user_permissions': list(Permission.objects.values_list('pk', flat=True)),
                     '_save': 'Guardar'}
            for ruta, payload in (
                (reverse('admin:auth_user_change', args=[usuario.pk]), datos),
                (reverse('admin:auth_user_delete', args=[usuario.pk]), {'post': 'yes'}),
                (reverse('admin:auth_user_password_change', args=[usuario.pk]),
                 {'password1': self.datos['password1'], 'password2': self.datos['password2']}),
            ):
                with self.subTest(ruta=ruta):
                    self.assertEqual(self.client.post(ruta, payload).status_code, 403)
        for ruta, payload in (
            (reverse('admin:auth_user_add'), {**self.datos, 'is_superuser': 'on'}),
            (reverse('admin:auth_user_changelist'), {'action': 'delete_selected', '_selected_action': self.root.pk, 'post': 'yes'}),
            (reverse('admin:auth_group_add'), {'name': 'Escalada', 'permissions': permisos}),
            (reverse('admin:auth_group_change', args=[grupo.pk]), {'name': 'Alterado', 'permissions': list(Permission.objects.values_list('pk', flat=True))}),
            (reverse('admin:auth_group_delete', args=[grupo.pk]), {'post': 'yes'}),
            (reverse('admin:auth_group_changelist'), {'action': 'delete_selected', '_selected_action': grupo.pk, 'post': 'yes'}),
        ):
            with self.subTest(ruta=ruta):
                self.assertEqual(self.client.post(ruta, payload).status_code, 403)
        self.assertEqual(list(User.objects.order_by('pk').values()), antes)
        for pk, grupos, permisos_directos in relaciones:
            usuario = User.objects.get(pk=pk)
            self.assertEqual(set(usuario.groups.values_list('pk', flat=True)), grupos)
            self.assertEqual(set(usuario.user_permissions.values_list('pk', flat=True)), permisos_directos)
        self.assertEqual(list(grupo.permissions.order_by('pk').values_list('pk', flat=True)), permisos)
        grupo.refresh_from_db()
        self.assertEqual(grupo.name, 'Administrador')
        self.assertFalse(Group.objects.filter(name='Escalada').exists())
        self.assertEqual(LogEntry.objects.count(), 0)

    def test_superusuario_conserva_escrituras_tecnicas(self):
        self.client.force_login(self.root)
        response = self.client.post(reverse('admin:auth_user_change', args=[self.normal.pk]), {
            'username': self.normal.username, 'is_active': 'on', 'is_staff': 'on',
            'is_superuser': 'on', '_save': 'Guardar',
            'date_joined_0': timezone.localdate().isoformat(), 'date_joined_1': '12:00:00',
        })
        self.assertEqual(response.status_code, 302)
        self.normal.refresh_from_db()
        self.assertTrue(self.normal.is_superuser)
        self.assertEqual(self.client.post(reverse('admin:auth_group_add'), {
            'name': 'Tecnico', 'permissions': Permission.objects.first().pk, '_save': 'Guardar',
        }).status_code, 302)
        self.assertTrue(Group.objects.get(name='Tecnico').permissions.exists())

    def test_usuario_normal_no_accede_admin(self):
        self.client.force_login(self.normal)
        self.assertEqual(self.client.post(reverse('admin:auth_user_change', args=[self.normal.pk]), {'is_superuser': 'on'}).status_code, 302)
        self.normal.refresh_from_db()
        self.assertFalse(self.normal.is_superuser)

    def test_configurar_roles_reemplaza_permisos_historicos(self):
        grupo = Group.objects.get(name='Administrador')
        grupo.permissions.set(Permission.objects.all())
        call_command('configurar_roles', stdout=StringIO())
        self.assertEqual(User.objects.get(pk=self.admin.pk).get_all_permissions(), PERMISOS_ADMINISTRADOR)
        self.assertFalse(grupo.permissions.filter(codename='change_group').exists())

    def test_rol_canonico_no_eleva_usuario_propio_ni_ajeno(self):
        self.client.force_login(self.admin)
        for usuario in (self.normal, self.admin):
            with self.subTest(usuario=usuario.username):
                response = self.client.post(reverse('admin:auth_user_change', args=[usuario.pk]), {
                    'username': usuario.username, 'is_active': 'on', 'is_staff': 'on',
                    'is_superuser': 'on', '_save': 'Guardar',
                    'date_joined_0': timezone.localdate().isoformat(), 'date_joined_1': '12:00:00',
                })
                usuario.refresh_from_db()
                self.assertFalse(usuario.is_superuser)
                self.assertEqual(response.status_code, 403)

    def test_rol_canonico_no_modifica_permisos_del_grupo(self):
        self.client.force_login(self.admin)
        grupo = Group.objects.get(name='Administrador')
        response = self.client.post(reverse('admin:auth_group_change', args=[grupo.pk]), {
            'name': grupo.name, 'permissions': list(Permission.objects.values_list('pk', flat=True)),
            '_save': 'Guardar',
        })
        self.assertFalse(grupo.permissions.filter(content_type__app_label='token_blacklist').exists())
        self.assertEqual(response.status_code, 403)

    def test_miembro_sin_permisos_e_inactivo_no_autoriza(self):
        grupo = Group.objects.get(name='Administrador')
        grupo.permissions.clear()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(self.url, self.datos).status_code, 403)
        self.assertNotContains(self.client.get(reverse('landing')), 'Gestión de administradores')
        self.root.is_active = False
        self.root.save()
        self.client.force_login(self.root)
        self.assertEqual(self.client.post(self.url, self.datos).status_code, 302)
        self.assertFalse(User.objects.filter(username='pepe').exists())

    def test_api_me_no_admite_escrituras(self):
        from rest_framework.test import APIClient
        cliente = APIClient()
        cliente.force_authenticate(self.admin)
        for metodo in ('post', 'put', 'patch', 'delete'):
            response = getattr(cliente, metodo)(reverse('user_me'),
                data={'is_superuser': True}, format='json')
            self.assertEqual(response.status_code, 405)
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.is_superuser)


class AltaConcurrenteTests(TransactionTestCase):
    def test_dos_altas_misma_identidad_solo_confirman_una(self):
        from concurrent.futures import ThreadPoolExecutor
        from contextlib import contextmanager
        from threading import Barrier
        from django.db import connection, connections
        from core.services.identidad import serializar_identidad
        if connection.vendor != 'postgresql':
            self.skipTest('Requiere PostgreSQL y conexiones independientes')
        call_command('configurar_roles', stdout=StringIO())
        creador = User.objects.create_user('creador', is_staff=True)
        creador.groups.add(Group.objects.get(name='Administrador'))
        barrera = Barrier(2)

        @contextmanager
        def juntos():
            barrera.wait(timeout=10)
            with serializar_identidad():
                yield

        def alta():
            try:
                cliente = Client()
                cliente.force_login(User.objects.get(pk=creador.pk))
                return cliente.post(reverse('gestion_administradores'), {
                    'username': 'duplicado', 'email': 'duplicado@example.com',
                    'password1': 'Rio!Litoral-9xQ482', 'password2': 'Rio!Litoral-9xQ482',
                }).status_code
            finally:
                connections['default'].close()

        with patch('core.views_administradores.serializar_identidad', juntos), ThreadPoolExecutor(max_workers=2) as worker:
            futuros = [worker.submit(alta) for _ in range(2)]
            self.assertEqual(sorted(f.result(timeout=20) for f in futuros), [200, 302])
        nuevo = User.objects.get(username='duplicado')
        self.assertFalse(nuevo.is_superuser)
        self.assertEqual(nuevo.get_all_permissions(), PERMISOS_ADMINISTRADOR)
        self.assertEqual(LogEntry.objects.filter(object_id=str(nuevo.pk)).count(), 1)
