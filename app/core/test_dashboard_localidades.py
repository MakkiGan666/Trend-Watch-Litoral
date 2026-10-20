from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.localidades import DEPARTAMENTOS
from core.models import Categoria, Locacion, Publicacion, PublicacionTema, Tema


class DashboardDepartamentosTests(TestCase):
    def test_catalogo_completo_y_asociaciones_sin_modificar_publicaciones(self):
        user = get_user_model().objects.create_superuser('test_departamentos', password='test-only-password')
        self.client.force_login(user)
        directa = Publicacion.objects.create(hash_origen='directa', titulo='Con departamento', contenido='Texto', departamento='capital')
        por_municipio = Publicacion.objects.create(hash_origen='municipio', titulo='Con municipio', contenido='Texto')
        Locacion.objects.create(id_publicacion_api=por_municipio, location='El Soberbio', latitud=0, longitud=0)
        desconocida = Publicacion.objects.create(hash_origen='desconocida', titulo='Sin datos', contenido='Texto', departamento='no-existe')
        salud = Categoria.objects.create(nombre_categoria='Salud')
        sociedad = Categoria.objects.create(nombre_categoria='Sociedad')
        for categoria in [salud, salud, sociedad]:
            tema = Tema.objects.create(id_categoria=categoria, descripcion='Tema de prueba')
            PublicacionTema.objects.create(id_publicacion_api=directa, id_temas=tema)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['departamentos']), 17)
        for departamento in DEPARTAMENTOS:
            self.assertContains(response, f'<option value="{departamento["slug"]}">{departamento["nombre"]}</option>')
        rows = {p.pk: p for p in response.context['publicaciones']}
        self.assertEqual(rows[directa.pk].dashboard_departamentos, ['capital'])
        self.assertEqual(rows[por_municipio.pk].dashboard_departamentos, ['guarani'])
        self.assertEqual(rows[desconocida.pk].dashboard_departamentos, [])
        self.assertEqual(rows[directa.pk].dashboard_categorias, sorted([salud.pk, sociedad.pk]))
        self.assertEqual(rows[desconocida.pk].dashboard_categorias, [])
        self.assertContains(response, f'<option value="{salud.pk}">Salud</option>')
        self.assertContains(response, 'Sin categoría asignada')
        self.assertNotContains(response, 'id="dashboard-analysis"')
        self.assertNotContains(response, 'Cómo funciona')
        por_municipio.refresh_from_db()
        self.assertEqual(por_municipio.departamento, '')
