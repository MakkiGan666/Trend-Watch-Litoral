from datetime import datetime, timezone

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from core.models import Categoria, Locacion, Publicacion, PublicacionTema, Sentimiento, Tema


class DashboardAnaliticoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = get_user_model().objects.create_superuser('analitica_root', 'root@example.com', None)
        cls.admin = get_user_model().objects.create_user('analitica_admin', is_staff=True)
        cls.admin.user_permissions.set(Permission.objects.all())
        cls.lector = get_user_model().objects.create_user('analitica_lector')

    def noticia(self, clave, **extra):
        return Publicacion.objects.create(hash_origen=clave, titulo=clave, contenido='Texto', fecha_captura=datetime(2026, 10, 20, 12, tzinfo=timezone.utc), **extra)

    def test_solo_superusuario_y_solo_consulta(self):
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 302)
        for usuario in (self.admin, self.lector):
            self.client.force_login(usuario)
            self.assertEqual(self.client.get(reverse('dashboard')).status_code, 403)
        self.client.force_login(self.root)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)
        self.assertEqual(self.client.post(reverse('dashboard')).status_code, 405)

    def test_cuenta_analisis_real_no_marca_y_separa_conflictos(self):
        pendiente = self.noticia('pendiente', procesado_ia=True)
        analizada = self.noticia('analizada', procesado_ia=False)
        conflicto = self.noticia('conflicto')
        invalida = self.noticia('invalida')
        Sentimiento.objects.create(id_publicacion_api=analizada, polaridad=0, confianza=.8)
        for valor in (.1, -.1):
            Sentimiento.objects.create(id_publicacion_api=conflicto, polaridad=valor, confianza=.8)
        Sentimiento.objects.create(id_publicacion_api=invalida, polaridad=2, confianza=.8)
        self.client.force_login(self.root)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['resumen'], {'total': 4, 'analizadas': 1, 'pendientes': 1, 'inconsistentes': 2})
        self.assertEqual({f['nombre']: f['total'] for f in response.context['sentimientos']}, {'Positivo': 0, 'Neutral': 1, 'Negativo': 0})
        self.assertEqual(Sentimiento.objects.count(), 4)

    def test_filtros_combinados_y_asociaciones_no_duplican(self):
        n = self.noticia('coincide', fuente='Fuente A', departamento='capital', fecha_publicacion=datetime(2026, 10, 1, 12, tzinfo=timezone.utc))
        c = Categoria.objects.create(nombre_categoria='Salud')
        for numero in range(2):
            t = Tema.objects.create(descripcion=str(numero), id_categoria=c)
            PublicacionTema.objects.create(id_publicacion_api=n, id_temas=t)
        Locacion.objects.create(id_publicacion_api=n, location='Posadas', latitud=-27.36, longitud=-55.9)
        self.noticia('afuera', fuente='Fuente B')
        self.client.force_login(self.root)
        response = self.client.get(reverse('dashboard'), {'desde': '2026-10-01', 'hasta': '2026-10-01', 'categoria': c.pk, 'departamento': 'capital', 'fuente': 'Fuente A'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['resumen']['total'], 1)
        self.assertEqual(response.context['categorias'][0]['total'], 1)
        self.assertEqual(next(d['total'] for d in response.context['departamentos'] if d['nombre'] == 'Capital'), 1)

    def test_fechas_locales_y_captura_si_no_hay_fecha_del_medio(self):
        self.noticia('medianoche', fecha_publicacion=datetime(2026, 10, 2, 1, tzinfo=timezone.utc))
        self.noticia('captura')
        self.client.force_login(self.root)
        response = self.client.get(reverse('dashboard'), {'desde': '2026-10-01', 'hasta': '2026-10-01'})
        self.assertEqual(response.context['resumen']['total'], 1)
        self.assertEqual(response.context['serie'][0]['fecha'], '01/10/2026')

    def test_sin_limite_100_y_estado_vacio(self):
        Publicacion.objects.bulk_create([Publicacion(hash_origen=f'fila-{i}', titulo=str(i), contenido='Texto') for i in range(115)])
        self.client.force_login(self.root)
        self.assertEqual(self.client.get(reverse('dashboard')).context['resumen']['total'], 115)
        response = self.client.get(reverse('dashboard'), {'hasta': '2020-01-01'})
        self.assertEqual(response.context['resumen']['total'], 0)
        self.assertContains(response, 'Sin publicaciones para estos filtros')

    def test_filtros_invalidos_rechazados(self):
        self.client.force_login(self.root)
        for params in ({'desde': 'fecha'}, {'desde': '2026-10-22', 'hasta': '2026-01-01'}, {'categoria': '999999'}, {'departamento': 'inexistente'}):
            response = self.client.get(reverse('dashboard'), params)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.context['resumen']['total'], 0)
