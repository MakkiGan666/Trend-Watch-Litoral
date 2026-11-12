from datetime import datetime, timezone

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from core.models import (
    Categoria, ClicPublicacion, Comentario, Locacion, Publicacion,
    PublicacionTema, Sentimiento, Tema, ValoracionPublicacion,
)


class DashboardAnaliticoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = get_user_model().objects.create_superuser('analitica_root', 'root@example.com', None)
        cls.admin = get_user_model().objects.create_user('analitica_admin', is_staff=True)
        cls.admin.user_permissions.set(Permission.objects.all())
        cls.lector = get_user_model().objects.create_user('analitica_lector')

    def noticia(self, clave, **extra):
        return Publicacion.objects.create(hash_origen=clave, titulo=clave, contenido='Texto', fecha_captura=datetime(2026, 10, 20, 12, tzinfo=timezone.utc), **extra)

    def test_fechas_conservan_respaldo_nativo_y_valores_iso(self):
        self.client.force_login(self.root)
        response = self.client.get(reverse('dashboard'), {
            'desde': '2024-02-29', 'hasta': '2026-10-31',
        })
        self.assertContains(response, 'type="date" name="desde" value="2024-02-29"')
        self.assertContains(response, 'type="date" name="hasta" value="2026-10-31"')
        self.assertContains(response, 'id="id_desde-calendar"', count=1)
        self.assertContains(response, 'id="id_hasta-calendar"', count=1)
        self.assertContains(response, 'aria-label="Elegir fecha: Desde"')
        self.assertContains(response, 'aria-label="Elegir fecha: Hasta"')

    def test_solo_superusuarios_y_solo_consulta(self):
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 302)
        for usuario in (self.lector, self.admin):
            self.client.force_login(usuario)
            self.assertEqual(self.client.get(reverse('dashboard')).status_code, 403)
        self.client.force_login(self.root)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)
        self.assertEqual(self.client.post(reverse('dashboard')).status_code, 405)

    def test_sin_analisis_muestra_estado_claro_y_conserva_conteos_reales(self):
        self.noticia('sin-analisis')
        self.client.force_login(self.root)
        dashboard = self.client.get(reverse('dashboard'))
        publicaciones = self.client.get(reverse('publicaciones'))
        self.assertEqual(dashboard.context['resumen']['analizadas'], 0)
        self.assertContains(dashboard, 'Aún sin análisis')
        self.assertContains(dashboard, 'Sin casos')
        self.assertContains(dashboard, '1 publicación sin análisis disponible')
        self.assertContains(publicaciones, 'Aún sin análisis')

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
        self.assertEqual(response.context['resumen'], {
            'total': 4, 'articulos_completos': 4, 'fichas_rss': 0,
            'sin_cuerpo_sin_ficha': 0, 'analizadas': 1, 'pendientes': 1,
            'inconsistentes': 2,
        })
        self.assertEqual({f['nombre']: f['total'] for f in response.context['sentimientos']}, {'Positivo': 0, 'Neutral': 1, 'Negativo': 0})
        self.assertEqual(Sentimiento.objects.count(), 4)

    def test_participacion_filtrada_cuenta_clics_votos_y_estados_de_comentarios(self):
        incluida = self.noticia('participacion-incluida', fuente='Fuente A')
        excluida = self.noticia('participacion-excluida', fuente='Fuente B')
        ValoracionPublicacion.objects.create(
            publicacion=incluida, usuario=self.lector, sentimiento='positivo',
        )
        ValoracionPublicacion.objects.create(
            publicacion=incluida, usuario=self.admin, sentimiento='neutral',
        )
        ValoracionPublicacion.objects.create(
            publicacion=excluida, usuario=self.lector, sentimiento='negativo',
        )
        ClicPublicacion.objects.create(publicacion=incluida, usuario=self.lector)
        ClicPublicacion.objects.create(publicacion=incluida, usuario=self.admin)
        ClicPublicacion.objects.create(publicacion=excluida, usuario=self.lector)
        for estado in (
            Comentario.Estado.PUBLICADO,
            Comentario.Estado.PENDIENTE,
            Comentario.Estado.RECHAZADO,
        ):
            Comentario.objects.create(
                publicacion=incluida, autor=self.lector,
                texto=f'Comentario {estado}', estado=estado,
            )
        Comentario.objects.create(
            publicacion=excluida, autor=self.lector, texto='Fuera del filtro',
            estado=Comentario.Estado.PUBLICADO,
        )

        self.client.force_login(self.root)
        response = self.client.get(reverse('dashboard'), {'fuente': 'Fuente A'})

        self.assertEqual(response.context['participacion'], {
            'clics': 2,
            'valoraciones': 2,
            'comentarios_publicados': 1,
            'comentarios_pendientes': 1,
            'comentarios_total': 3,
        })
        self.assertEqual(
            {fila['nombre']: fila['total'] for fila in response.context['valoraciones_lectores']},
            {'Positivo': 1, 'Neutral': 1, 'Negativo': 0},
        )
        self.assertContains(response, 'Participación de lectores')

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

    def test_secciones_de_el_territorio_se_agrupan_como_una_fuente(self):
        self.noticia('archivo', fuente='El Territorio (Archivo)')
        self.noticia('policiales', fuente='El Territorio (Policiales)')
        self.noticia('otra', fuente='Otra fuente (Regional)')
        self.client.force_login(self.root)

        response = self.client.get(reverse('dashboard'))
        self.assertEqual(
            {fila['nombre']: fila['total'] for fila in response.context['fuentes']},
            {'El Territorio': 2, 'Otra fuente (Regional)': 1},
        )
        self.assertEqual(
            [valor for valor, _ in response.context['filtros'].fields['fuente'].choices],
            ['', 'El Territorio', 'Otra fuente (Regional)'],
        )

        filtrada = self.client.get(reverse('dashboard'), {'fuente': 'El Territorio'})
        self.assertEqual(filtrada.status_code, 200)
        self.assertEqual(filtrada.context['resumen']['total'], 2)
        self.assertEqual(filtrada.context['fuentes'][0]['nombre'], 'El Territorio')

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

    def test_escala_diaria_proporcional_con_dias_ausentes(self):
        for dia in (1, 2, 31):
            self.noticia(f'dia-{dia}', fecha_publicacion=datetime(2026, 10, dia, 12, tzinfo=timezone.utc))
        self.client.force_login(self.root)
        response = self.client.get(reverse('dashboard'))
        serie = response.context['serie']
        self.assertFalse(response.context['mensual'])
        self.assertEqual([f['fecha'] for f in serie], ['01/10/2026', '02/10/2026', '31/10/2026'])
        self.assertEqual([f['x'] for f in serie], ['30.00', '51.33', '670.00'])
        self.assertEqual(response.context['puntos'], '30.00,35.00 51.33,35.00 670.00,35.00')

    def test_escala_mensual_con_huecos_y_cambio_de_anio(self):
        for i, (anio, mes) in enumerate(((2025, 12), (2026, 1), (2026, 6))):
            self.noticia(f'mes-{i}', fecha_publicacion=datetime(anio, mes, 1, 12, tzinfo=timezone.utc))
        self.client.force_login(self.root)
        response = self.client.get(reverse('dashboard'))
        self.assertTrue(response.context['mensual'])
        serie = response.context['serie']
        self.assertEqual([f['fecha'] for f in serie], ['12/2025', '01/2026', '06/2026'])
        self.assertEqual([f['x'] for f in serie], ['30.00', '136.67', '670.00'])
        self.assertEqual([f['total'] for f in serie], [1, 1, 1])

    def test_escala_un_periodo_y_conjunto_vacio(self):
        self.client.force_login(self.root)
        self.assertEqual(self.client.get(reverse('dashboard')).context['puntos'], '')
        self.noticia('unica')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['puntos'], '30.00,35.00')
