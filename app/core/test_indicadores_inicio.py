from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from core.models import Publicacion, Sentimiento


class IndicadoresInicioTests(TestCase):
    def test_visibilidad_y_conteo_coinciden_con_dashboard(self):
        root = get_user_model().objects.create_superuser('inicio_root', 'inicio@example.com', None)
        admin = get_user_model().objects.create_user('inicio_admin', is_staff=True)
        admin.user_permissions.set(Permission.objects.all())
        lector = get_user_model().objects.create_user('inicio_lector')
        for usuario in (None, admin, lector):
            self.client.logout()
            if usuario:
                self.client.force_login(usuario)
            with patch('core.views.resumen_publicaciones') as resumen:
                response = self.client.get(reverse('landing'))
                resumen.assert_not_called()
            self.assertNotContains(response, 'id="inicio-indicadores"')
        noticia = Publicacion.objects.create(hash_origen='inicio-analizada', titulo='Noticia', contenido='Texto')
        Sentimiento.objects.create(id_publicacion_api=noticia, polaridad=.6, confianza=.9)
        Publicacion.objects.create(hash_origen='inicio-pendiente', titulo='Otra', contenido='Texto', procesado_ia=True)
        self.client.force_login(root)
        inicio = self.client.get(reverse('landing'))
        dashboard = self.client.get(reverse('dashboard'))
        self.assertContains(inicio, 'id="inicio-indicadores"')
        self.assertEqual(inicio.context['indicadores_inicio'], dashboard.context['resumen'])
        self.assertEqual(inicio.context['indicadores_inicio']['pendientes'], 1)
        html = inicio.content.decode()
        self.assertLess(html.index('id="inicio-indicadores"'), html.index('id="news-heading-salud"'))
        self.assertIn('news-trends-title', html)
        self.assertIn('exchange-rates', html)
