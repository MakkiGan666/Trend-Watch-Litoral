from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse


class NavegacionAdminTests(TestCase):
    def test_orden_administradores_y_ocultamiento_para_visitantes(self):
        root = get_user_model().objects.create_superuser('nav_root', 'nav@example.com', None)
        admin = get_user_model().objects.create_user('nav_admin', is_staff=True)
        admin.user_permissions.set(Permission.objects.all())
        self.client.force_login(root)
        for ruta in ('landing', 'categorias', 'publicaciones', 'dashboard', 'gestion_administradores'):
            response = self.client.get(reverse(ruta))
            self.assertEqual(response.status_code, 200)
            html = response.content.decode()
            nav = html[html.index('class="nav__links"'):html.index('class="nav__act"')]
            posiciones = [nav.index('>Inicio<'), nav.index('>Publicaciones<'), nav.index('>Categorías'), nav.index('>Dashboard<'), nav.index('>Administradores<')]
            self.assertEqual(posiciones, sorted(posiciones))
            self.assertEqual(html.count('href="/administradores/"'), 1)
            if ruta == 'gestion_administradores':
                self.assertIn('href="/administradores/" aria-current="page"', nav)
                self.assertContains(response, 'data-password-toggle="id_password1"', count=1)
                self.assertContains(response, 'data-password-toggle="id_password2"', count=1)
        self.client.force_login(admin)
        for ruta in ('landing', 'categorias', 'publicaciones'):
            response = self.client.get(reverse(ruta))
            self.assertContains(response, 'href="/publicaciones/"')
            self.assertContains(response, 'href="/dashboard/"')
            self.assertNotContains(response, 'href="/administradores/"')
        self.client.logout()
        response = self.client.get(reverse('landing'))
        self.assertNotContains(response, 'href="/dashboard/"')
        self.assertNotContains(response, 'href="/publicaciones/"')
