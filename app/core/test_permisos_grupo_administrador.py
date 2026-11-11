"""Regresión: el grupo Administrador opera el panel sin ser superusuario."""
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from core.roles import PERMISOS_PANEL

User = get_user_model()

RUTAS_ADMINISTRATIVAS = (
    'dashboard', 'publicaciones', 'gestion_administradores',
    'listado_administradores', 'listado_usuarios',
)


class GrupoAdministradorSinSuperusuarioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('configurar_roles', stdout=StringIO())
        cls.grupo = Group.objects.get(name='Administrador')
        # Igual que el alta del panel: staff, sin superusuario y sólo por grupo.
        cls.admin = User.objects.create_user('admin_grupo', is_staff=True)
        cls.admin.groups.add(cls.grupo)
        cls.lector = User.objects.create_user('lector_general')
        cls.lector.groups.add(Group.objects.get(name='Usuario'))
        cls.solo_edicion = User.objects.create_user('solo_edicion')
        cls.solo_edicion.user_permissions.add(
            Permission.objects.get(content_type__app_label='core', codename='change_publicacion'),
        )

    def test_administrador_no_es_superusuario_y_accede_al_panel(self):
        self.assertFalse(self.admin.is_superuser)
        self.assertTrue(self.admin.groups.filter(name='Administrador').exists())
        self.assertFalse(self.admin.user_permissions.exists())
        self.client.force_login(self.admin)
        for ruta in RUTAS_ADMINISTRATIVAS:
            with self.subTest(ruta=ruta):
                self.assertEqual(self.client.get(reverse(ruta)).status_code, 200)
        dashboard = self.client.get(reverse('dashboard'))
        self.assertNotContains(dashboard, 'Panel de superusuarios')
        listado = self.client.get(reverse('listado_administradores'))
        self.assertIn('admin_grupo', {cuenta.username for cuenta in listado.context['pagina']})

    def test_administrador_ve_los_enlaces_administrativos(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse('landing')).content.decode()
        nav = html[html.index('class="nav__links"'):html.index('class="nav__act"')]
        for ruta in ('publicaciones', 'dashboard', 'gestion_administradores'):
            with self.subTest(ruta=ruta):
                self.assertIn(f'href="{reverse(ruta)}"', nav)
        gestion = self.client.get(reverse('gestion_administradores'))
        for ruta in ('listado_administradores', 'listado_usuarios'):
            self.assertContains(gestion, f'href="{reverse(ruta)}"')

    def test_administrador_no_escribe_usuarios_ni_grupos_en_django_admin(self):
        self.client.force_login(self.admin)
        # Puede consultar el Admin, pero usuarios y grupos son de sólo lectura.
        self.assertEqual(self.client.get(reverse('admin:index')).status_code, 200)
        self.assertEqual(self.client.get(reverse('admin:auth_user_changelist')).status_code, 200)
        prohibidas = (
            ('get', reverse('admin:auth_user_add'), None),
            ('post', reverse('admin:auth_user_add'), {
                'username': 'intruso', 'password1': 'Rio!Litoral-9xQ482', 'password2': 'Rio!Litoral-9xQ482',
            }),
            ('post', reverse('admin:auth_user_change', args=[self.admin.pk]), {
                'username': 'admin_grupo', 'is_superuser': 'on', 'is_staff': 'on', 'is_active': 'on',
            }),
            ('post', reverse('admin:auth_user_delete', args=[self.lector.pk]), {'post': 'yes'}),
            ('get', reverse('admin:auth_group_add'), None),
            ('post', reverse('admin:auth_group_add'), {'name': 'Escalada'}),
            ('post', reverse('admin:auth_group_change', args=[self.grupo.pk]), {
                'name': 'Alterado', 'permissions': list(Permission.objects.values_list('pk', flat=True)),
            }),
            ('post', reverse('admin:auth_group_delete', args=[self.grupo.pk]), {'post': 'yes'}),
        )
        permisos_grupo = set(self.grupo.permissions.values_list('pk', flat=True))
        for metodo, url, datos in prohibidas:
            with self.subTest(metodo=metodo, url=url):
                respuesta = getattr(self.client, metodo)(url, datos or {})
                self.assertEqual(respuesta.status_code, 403)
        self.admin.refresh_from_db()
        self.grupo.refresh_from_db()
        self.assertFalse(self.admin.is_superuser)
        self.assertEqual(self.grupo.name, 'Administrador')
        self.assertEqual(set(self.grupo.permissions.values_list('pk', flat=True)), permisos_grupo)
        self.assertTrue(User.objects.filter(pk=self.lector.pk).exists())
        self.assertFalse(User.objects.filter(username='intruso').exists())
        self.assertFalse(Group.objects.filter(name='Escalada').exists())

    def test_usuario_general_sigue_sin_acceso(self):
        for ruta in RUTAS_ADMINISTRATIVAS:
            with self.subTest(ruta=ruta, usuario='anonimo'):
                self.assertEqual(self.client.get(reverse(ruta)).status_code, 302)
        self.client.force_login(self.lector)
        for ruta in RUTAS_ADMINISTRATIVAS:
            with self.subTest(ruta=ruta, usuario='lector'):
                self.assertEqual(self.client.get(reverse(ruta)).status_code, 403)
        html = self.client.get(reverse('landing')).content.decode()
        for ruta in ('publicaciones', 'dashboard', 'gestion_administradores'):
            self.assertNotIn(f'href="{reverse(ruta)}"', html)
        self.assertNotEqual(self.client.get(reverse('admin:index')).status_code, 200)

    def test_enlace_publicaciones_exige_los_mismos_permisos_que_la_vista(self):
        # Sólo change_publicacion no alcanza para el panel: sin enlace y sin acceso.
        self.client.force_login(self.solo_edicion)
        self.assertEqual(self.client.get(reverse('publicaciones')).status_code, 403)
        html = self.client.get(reverse('categorias')).content.decode()
        self.assertNotIn(f'href="{reverse("publicaciones")}"', html)

    def _menus_portada(self):
        respuesta = self.client.get(reverse('landing'))
        self.assertEqual(respuesta.status_code, 200)
        html = respuesta.content.decode()
        superior = html[html.index('class="nav__links"'):html.index('class="nav__act"')]
        pie = html[html.index('<h4>Plataforma</h4>'):]
        pie = pie[:pie.index('</div>')]
        return superior, pie

    def test_portada_oculta_publicaciones_sin_permisos_del_panel(self):
        enlace = f'href="{reverse("publicaciones")}"'
        # Control: con PERMISOS_PANEL el enlace aparece en ambas zonas.
        self.client.force_login(self.admin)
        superior, pie = self._menus_portada()
        self.assertIn(enlace, superior)
        self.assertIn(enlace, pie)
        # Sólo change_publicacion, sin grupo Administrador ni panel completo.
        self.assertTrue(self.solo_edicion.has_perm('core.change_publicacion'))
        self.assertFalse(self.solo_edicion.groups.filter(name='Administrador').exists())
        self.assertFalse(self.solo_edicion.has_perms(PERMISOS_PANEL))
        self.client.force_login(self.solo_edicion)
        superior, pie = self._menus_portada()
        self.assertNotIn(enlace, superior)
        self.assertNotIn(enlace, pie)
        self.assertEqual(self.client.get(reverse('publicaciones')).status_code, 403)
