from io import StringIO
from django.core.management import call_command
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate
from unittest.mock import patch
from core.models import Publicacion, RegistroDatos, Sentimiento
from core.views import crear_o_ingestar_publicacion, disparar_ingesta

# Create your tests here.

class IngestaTestCase(TestCase):
    def setUp(self):
        self.registro = RegistroDatos.objects.create(
            fuentes_api="Prueba Feed",
            fecha_ejecucion=timezone.now(),
            estado="EXITO",
            lenguaje="es"
        )

    def test_crear_publicacion(self):
        pub = Publicacion.objects.create(
            hash_origen="hash123test",
            fuente="El Territorio",
            titulo="Noticia de Prueba",
            contenido="Contenido de prueba",
            url="https://ejemplo.com",
            id_registro=self.registro
        )
        self.assertEqual(pub.titulo, "Noticia de Prueba")
        self.assertFalse(pub.procesado_ia)


class IngestaRSSTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        call_command('configurar_roles', stdout=StringIO())
        self.user = get_user_model().objects.create_user(username='prueba_ingesta')
        self.user.groups.add(Group.objects.get(name='Administrador'))
        self.registro = RegistroDatos.objects.create(
            fuentes_api='Prueba RSS', fecha_ejecucion=timezone.now(),
            estado='EXITO', lenguaje='es',
        )
        self.resumen = {
            'status': 'EXITO', 'capturados': 1,
            'registro_id': self.registro.pk,
        }

    def request(self, ruta):
        request = self.factory.post(ruta, {}, format='json')
        force_authenticate(request, user=self.user)
        return request

    @patch('core.views.compute_probabilistic_sentiment', return_value={'confidence_score': 0.8})
    @patch('core.views.analyze_sentiment_lexicon', return_value=0.5)
    @patch('core.views.fetch_and_store_elterritorio')
    def test_rss_procesa_solo_publicaciones_del_registro(self, scraper, lexicon, probabilistico):
        nueva = Publicacion.objects.create(
            hash_origen='nueva', titulo='Noticia', contenido='Contenido',
            id_registro=self.registro,
        )
        anterior = Publicacion.objects.create(hash_origen='anterior', contenido='Anterior')
        procesada = Publicacion.objects.create(
            hash_origen='procesada', contenido='Procesada',
            id_registro=self.registro, procesado_ia=True,
        )
        scraper.return_value = dict(self.resumen, capturados=2)

        response = crear_o_ingestar_publicacion(self.request('/api/publicaciones/crear/'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['total_ingestadas'], 2)
        nueva.refresh_from_db()
        anterior.refresh_from_db()
        self.assertTrue(nueva.procesado_ia)
        self.assertFalse(anterior.procesado_ia)
        self.assertEqual(Sentimiento.objects.get(id_publicacion_api=nueva).polaridad, 0.5)
        self.assertFalse(Sentimiento.objects.filter(id_publicacion_api=anterior).exists())
        self.assertFalse(Sentimiento.objects.filter(id_publicacion_api=procesada).exists())
        lexicon.assert_called_once_with('Noticia Contenido')
        probabilistico.assert_called_once()

    @patch('core.views.analyze_sentiment_lexicon')
    @patch('core.views.fetch_and_store_elterritorio')
    def test_rss_sin_capturas_devuelve_total_cero(self, scraper, lexicon):
        scraper.return_value = dict(self.resumen, capturados=0)
        response = crear_o_ingestar_publicacion(self.request('/api/publicaciones/crear/'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['total_ingestadas'], 0)
        lexicon.assert_not_called()

    @patch('core.views.procesar_publicaciones_con_ia')
    @patch('core.views.compute_probabilistic_sentiment')
    @patch('core.views.analyze_sentiment_lexicon')
    @patch('core.views.fetch_and_store_elterritorio')
    def test_error_ingesta_detiene_ambas_rutas(self, scraper, lexicon, probabilistico, ia):
        parcial = Publicacion.objects.create(
            hash_origen='parcial', contenido='Guardada antes del error',
            id_registro=self.registro,
        )
        scraper.return_value = {'status': 'ERROR', 'detalle': 'Feed no disponible'}
        for vista, argumentos in ((crear_o_ingestar_publicacion, ()), (disparar_ingesta, ('misiones',))):
            with self.subTest(vista=vista.__name__):
                response = vista(self.request('/api/publicaciones/crear/'), *argumentos)
                self.assertEqual(response.status_code, 500)
                self.assertEqual(response.data['status'], 'error')
                self.assertEqual(response.data['mensaje_ingesta'], scraper.return_value)
        lexicon.assert_not_called()
        probabilistico.assert_not_called()
        ia.assert_not_called()
        parcial.refresh_from_db()
        self.assertFalse(parcial.procesado_ia)
        self.assertFalse(Sentimiento.objects.exists())

    @patch('core.views.procesar_publicaciones_con_ia', return_value='Análisis completado')
    @patch('core.views.fetch_and_store_elterritorio')
    def test_ingesta_categoria_exitosa_continua_con_ia(self, scraper, ia):
        scraper.return_value = self.resumen
        response = disparar_ingesta(self.request('/api/publicaciones/ingestar/misiones/'), 'misiones')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'success')
        self.assertEqual(response.data['mensaje_ingesta'], self.resumen)
        scraper.assert_called_once_with('misiones')
        ia.assert_called_once_with(batch_size=10)


class RolesPermisosTestCase(TestCase):
    def setUp(self):
        from rest_framework.test import APIClient
        call_command('configurar_roles', stdout=StringIO())
        self.api = APIClient()
        self.usuarios = {}
        for rol in ('Usuario', 'Administrador'):
            usuario = get_user_model().objects.create_user(
                username=rol.lower(), is_staff=rol == 'Administrador',
            )
            usuario.groups.add(Group.objects.get(name=rol))
            self.usuarios[rol] = usuario
        self.usuarios['Sin rol'] = get_user_model().objects.create_user(username='sin_rol')
        self.publicacion = Publicacion.objects.create(
            hash_origen='roles-prueba', titulo='Original', contenido='Contenido',
        )
        self.registro = RegistroDatos.objects.create(
            fuentes_api='RSS simulado', fecha_ejecucion=timezone.now(),
            estado='EXITO', lenguaje='es',
        )
        self.mocks = {}
        for nombre, resultado in (
            ('fetch_and_store_elterritorio', {'status': 'EXITO', 'capturados': 0, 'registro_id': self.registro.pk}),
            ('procesar_publicaciones_con_ia', 'Procesado'),
            ('analyze_sentiment_lexicon', 0.5),
            ('compute_probabilistic_sentiment', {'confidence_score': 0.8}),
        ):
            parche = patch('core.views.' + nombre, return_value=resultado)
            self.mocks[nombre] = parche.start()
            self.addCleanup(parche.stop)

    def autenticar(self, rol):
        from rest_framework_simplejwt.tokens import RefreshToken
        self.client.logout()
        self.api.credentials()
        if rol is not None:
            usuario = self.usuarios[rol]
            self.client.force_login(usuario)
            token = RefreshToken.for_user(usuario).access_token
            self.api.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    def estado_datos(self):
        from core.models import Locacion, Tema, PublicacionTema
        return tuple(tuple(modelo.objects.order_by('pk').values_list()) for modelo in (
            Publicacion, Sentimiento, Locacion, RegistroDatos, Tema, PublicacionTema,
        ))

    def test_lectura_publica_y_dashboard_por_permiso(self):
        for rol in (None, *self.usuarios):
            with self.subTest(rol=rol):
                self.autenticar(rol)
                self.assertEqual(self.client.get(f'/noticia/{self.publicacion.pk}/').status_code, 200)
                self.assertEqual(self.api.get('/api/publicaciones/').status_code, 200)
                self.assertEqual(self.api.get(f'/api/publicaciones/{self.publicacion.pk}/').status_code, 200)
                esperado = 302 if rol is None else (403 if rol == 'Sin rol' else 200)
                self.assertEqual(self.client.get('/dashboard/').status_code, esperado)

    def test_mutaciones_denegadas_no_tienen_efectos(self):
        pk = self.publicacion.pk
        operaciones = (
            lambda: self.client.post('/publicaciones/crear/', {'titulo': 'No autorizado', 'contenido': 'Texto', 'fuente': 'Manual', 'url': 'https://example.com'}),
            lambda: self.api.post('/api/publicaciones/crear/', {'titulo': 'No autorizado', 'contenido': 'Texto'}, format='json'),
            lambda: self.api.post('/api/publicaciones/crear/', {}, format='json'),
            lambda: self.api.patch(f'/api/publicaciones/{pk}/actualizar/', {'titulo': 'No autorizado'}, format='json'),
            lambda: self.api.put(f'/api/publicaciones/{pk}/actualizar/', {'contenido': 'No autorizado'}, format='json'),
            lambda: self.api.delete(f'/api/publicaciones/{pk}/eliminar/'),
            lambda: self.api.post('/api/publicaciones/ingestar/misiones/', {}, format='json'),
            lambda: self.client.post('/procesar-ia/'),
            lambda: self.api.post('/api/sentiment/batch-analyze/', {'comments': []}, format='json'),
            lambda: self.api.post(f'/api/publicaciones/{pk}/procesar-sentimiento/'),
        )
        for rol in (None, 'Usuario', 'Sin rol'):
            self.autenticar(rol)
            for indice, operacion in enumerate(operaciones):
                with self.subTest(rol=rol, operacion=indice):
                    antes = self.estado_datos()
                    response = operacion()
                    self.assertIn(response.status_code, (302, 401, 403))
                    self.assertEqual(self.estado_datos(), antes)
                    for mock in self.mocks.values():
                        mock.assert_not_called()

    def test_administrador_crea_edita_y_procesa(self):
        for rol in ('Administrador',):
            with self.subTest(rol=rol):
                self.autenticar(rol)
                response = self.client.post('/publicaciones/crear/', {
                    'titulo': f'HTML {rol}', 'fuente': 'Manual', 'contenido': 'Texto',
                    'url': f'https://example.com/{rol}',
                })
                self.assertEqual(response.status_code, 302)
                self.assertTrue(Publicacion.objects.filter(titulo=f'HTML {rol}').exists())
                response = self.api.post('/api/publicaciones/crear/', {
                    'titulo': f'API {rol}', 'contenido': 'Texto',
                }, format='json')
                self.assertEqual(response.status_code, 201)
                pk = response.data['id_publicacion_api']
                self.assertEqual(self.api.patch(f'/api/publicaciones/{pk}/actualizar/', {'titulo': 'Editada'}, format='json').status_code, 200)
                self.assertEqual(Publicacion.objects.get(pk=pk).titulo, 'Editada')
                self.assertEqual(self.api.post('/api/publicaciones/crear/', {}, format='json').status_code, 200)
                self.assertEqual(self.api.post('/api/publicaciones/ingestar/misiones/').status_code, 200)
                self.assertEqual(self.client.post('/procesar-ia/').status_code, 200)
                self.assertEqual(self.api.post('/api/sentiment/batch-analyze/', {'comments': []}, format='json').status_code, 200)
                self.assertEqual(self.api.post(f'/api/publicaciones/{pk}/procesar-sentimiento/').status_code, 200)
                self.assertEqual(self.api.delete(f'/api/publicaciones/{pk}/eliminar/').status_code, 200)
                self.assertFalse(Publicacion.objects.filter(pk=pk).exists())
        self.mocks['fetch_and_store_elterritorio'].assert_called()
        self.mocks['procesar_publicaciones_con_ia'].assert_called()

    def test_get_no_ejecuta_scraping_ni_ia(self):
        for rol in (None, *self.usuarios):
            self.autenticar(rol)
            for ruta in (
                '/api/publicaciones/crear/', '/api/publicaciones/ingestar/misiones/',
                '/api/sentiment/batch-analyze/',
                f'/api/publicaciones/{self.publicacion.pk}/procesar-sentimiento/',
            ):
                with self.subTest(rol=rol, ruta=ruta):
                    self.assertIn(self.api.get(ruta).status_code, (401, 403, 405))
            self.assertEqual(self.client.get('/procesar-ia/').status_code, 405)
        for mock in self.mocks.values():
            mock.assert_not_called()

    def test_grupos_exactos_idempotentes_y_reutilizados(self):
        from core.roles import PERMISOS_ROLES
        pks = dict(Group.objects.filter(name__in=PERMISOS_ROLES).values_list('name', 'pk'))
        Group.objects.get(name='Usuario').permissions.add(Permission.objects.get(
            content_type__app_label='core', codename='delete_publicacion',
        ))
        call_command('configurar_roles', stdout=StringIO())
        call_command('configurar_roles', stdout=StringIO())
        self.assertEqual(dict(Group.objects.filter(name__in=PERMISOS_ROLES).values_list('name', 'pk')), pks)
        self.assertEqual(set(PERMISOS_ROLES), {'Usuario', 'Administrador'})
        for nombre, esperados in PERMISOS_ROLES.items():
            grupo = Group.objects.get(name=nombre)
            reales = {f'{p.content_type.app_label}.{p.codename}' for p in grupo.permissions.select_related('content_type')}
            self.assertEqual(reales, esperados)

    def test_admin_y_administracion_de_usuarios_roles(self):
        from django.contrib import admin
        from django.test import RequestFactory
        from django.contrib.auth.models import User
        for rol, usuario in self.usuarios.items():
            self.autenticar(rol)
            response = self.client.get('/admin/')
            self.assertEqual(response.status_code, 200 if rol == 'Administrador' else 302)
            request = RequestFactory().get('/admin/')
            request.user = usuario
            for modelo in (User, Group):
                model_admin = admin.site._registry[modelo]
                for accion in ('view', 'add', 'change', 'delete'):
                    self.assertEqual(getattr(model_admin, f'has_{accion}_permission')(request), rol == 'Administrador')

    def test_asignacion_por_comando_actualiza_flags_y_permisos(self):
        usuario = self.usuarios['Sin rol']
        for rol in ('Administrador', 'Usuario'):
            call_command('configurar_roles', usuario=usuario.username, rol=rol, stdout=StringIO())
            usuario.refresh_from_db()
            self.assertEqual(list(usuario.groups.values_list('name', flat=True)), [rol])
            self.assertEqual(usuario.is_staff, rol == 'Administrador')
            self.assertFalse(usuario.is_superuser)
            self.assertFalse(usuario.user_permissions.exists())

    def test_vistas_comprueban_permisos_y_no_nombres_de_grupos(self):
        usuario = self.usuarios['Sin rol']
        usuario.user_permissions.add(Permission.objects.get(content_type__app_label='core', codename='change_publicacion'))
        self.autenticar('Sin rol')
        response = self.api.patch(f'/api/publicaciones/{self.publicacion.pk}/actualizar/', {'titulo': 'Permiso directo'}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_perfil_informa_roles_actuales_y_no_inventa_usuario(self):
        for rol in self.usuarios:
            self.autenticar(rol)
            response = self.api.get('/api/auth/me/')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['roles'], [] if rol == 'Sin rol' else [rol.upper()])

    def test_permiso_de_creacion_manual_no_requiere_ia(self):
        usuario = self.usuarios['Sin rol']
        usuario.user_permissions.add(Permission.objects.get(
            content_type__app_label='core', codename='add_publicacion',
        ))
        self.autenticar('Sin rol')
        response = self.api.post('/api/publicaciones/crear/', {
            'titulo': 'Creación sin permiso IA', 'contenido': 'Texto',
        }, format='json')
        self.assertEqual(response.status_code, 201)
        publicacion = Publicacion.objects.get(pk=response.data['id_publicacion_api'])
        self.assertTrue(Sentimiento.objects.filter(id_publicacion_api=publicacion).exists())
        self.mocks['analyze_sentiment_lexicon'].assert_called_once()
        self.mocks['compute_probabilistic_sentiment'].assert_called_once()
        self.mocks['fetch_and_store_elterritorio'].assert_not_called()
        self.mocks['procesar_publicaciones_con_ia'].assert_not_called()
        # Crear no permite disparar el procesamiento IA independiente ni RSS.
        self.assertEqual(self.api.post('/api/publicaciones/crear/', {}, format='json').status_code, 403)
        self.assertEqual(self.client.post('/procesar-ia/').status_code, 403)

    def test_scraping_sin_permiso_ia_no_dispara_servicios(self):
        usuario = self.usuarios['Sin rol']
        usuario.user_permissions.add(Permission.objects.get(
            content_type__app_label='core', codename='ejecutar_scraping',
        ))
        self.autenticar('Sin rol')
        antes = self.estado_datos()
        self.assertEqual(self.api.post('/api/publicaciones/ingestar/misiones/', {}, format='json').status_code, 403)
        self.assertEqual(self.estado_datos(), antes)
        for mock in self.mocks.values():
            mock.assert_not_called()

    def test_permiso_usuario_es_solo_lectura(self):
        grupo = Group.objects.get(name='Usuario')
        self.assertEqual(set(grupo.permissions.values_list(
            'content_type__app_label', 'codename',
        )), {('core', 'view_publicacion')})

    def test_endpoint_alternativo_ia_protegido(self):
        from django.test import RequestFactory
        from django.contrib.auth.models import AnonymousUser
        from django.core.exceptions import PermissionDenied
        from core.services.gemini_cliente import disparar_ingesta as alternativa
        factory = RequestFactory()
        with patch('core.services.gemini_cliente.fetch_and_store_elterritorio') as scraper, patch('core.services.gemini_cliente.procesar_publicaciones_con_ia') as ia:
            for usuario in (AnonymousUser(), self.usuarios['Usuario'], self.usuarios['Sin rol']):
                request = factory.post('/alternativa/')
                request.user = usuario
                if usuario.is_authenticated:
                    with self.assertRaises(PermissionDenied):
                        alternativa(request, 'misiones')
                else:
                    self.assertEqual(alternativa(request, 'misiones').status_code, 302)
            request = factory.get('/alternativa/')
            request.user = self.usuarios['Administrador']
            self.assertEqual(alternativa(request, 'misiones').status_code, 405)
            scraper.assert_not_called()
            ia.assert_not_called()

    def test_configuracion_preserva_grupos_historicos_y_sus_miembros(self):
        grupos = [Group.objects.create(name=nombre) for nombre in ('Lector', 'Analista')]
        permiso = Permission.objects.get(content_type__app_label='core', codename='change_publicacion')
        for grupo in grupos:
            grupo.permissions.add(permiso)
        antiguo = get_user_model().objects.create_user(username='historico', is_staff=True)
        antiguo.groups.add(*grupos)
        antiguo.user_permissions.add(permiso)
        administrador = self.usuarios['Administrador']
        administrador.groups.add(*grupos)
        for _ in range(2):
            call_command('configurar_roles', stdout=StringIO())
        for grupo in grupos:
            self.assertTrue(Group.objects.filter(pk=grupo.pk, name=grupo.name).exists())
            self.assertEqual(list(grupo.permissions.values_list('pk', flat=True)), [permiso.pk])
            self.assertTrue(antiguo.groups.filter(pk=grupo.pk).exists())
            self.assertTrue(administrador.groups.filter(pk=grupo.pk).exists())
        antiguo.refresh_from_db()
        self.assertTrue(antiguo.is_staff)
        self.assertEqual(list(antiguo.user_permissions.values_list('pk', flat=True)), [permiso.pk])
        self.assertTrue(antiguo.has_perm('core.change_publicacion'))
        from rest_framework_simplejwt.tokens import RefreshToken
        self.api.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(antiguo).access_token}')
        self.assertEqual(self.api.get('/api/auth/me/').data['roles'], [])
        self.api.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(administrador).access_token}')
        self.assertEqual(self.api.get('/api/auth/me/').data['roles'], ['ADMINISTRADOR'])
        # La reasignación sólo afecta a la cuenta indicada; conserva los grupos históricos.
        call_command('configurar_roles', usuario=antiguo.username, rol='Usuario', stdout=StringIO())
        antiguo.refresh_from_db()
        self.assertFalse(antiguo.is_staff)
        self.assertFalse(antiguo.user_permissions.exists())
        self.assertEqual(list(antiguo.groups.values_list('name', flat=True)), ['Usuario'])
        for grupo in grupos:
            self.assertTrue(grupo.permissions.filter(pk=permiso.pk).exists())
            self.assertTrue(administrador.groups.filter(pk=grupo.pk).exists())

    def test_roles_historicos_no_se_pueden_asignar(self):
        from django.core.management.base import CommandError
        for rol in ('Lector', 'Analista'):
            with self.assertRaises(CommandError):
                call_command('configurar_roles', usuario='sin_rol', rol=rol, stdout=StringIO())
