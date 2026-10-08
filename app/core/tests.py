from io import StringIO
import json
import hashlib
import xml.etree.ElementTree as ET
from urllib.error import URLError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.contrib.auth.models import Group, Permission
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db import IntegrityError, OperationalError, connections
from rest_framework.test import APIRequestFactory, force_authenticate
from unittest.mock import call, patch
from core.models import Publicacion, RegistroDatos, Sentimiento
from core.views import disparar_ingesta
from core.scrapers.noticias import fetch_elterritorio_news
from core.serializers import PublicacionCreateSerializer, PublicacionUpdateSerializer


class PublicacionSerializersTestCase(SimpleTestCase):
    def payload(self, **changes):
        return {'titulo': ' Noticia ', 'contenido': ' Texto original ', **changes}

    def assert_invalid(self, serializer, field):
        self.assertFalse(serializer.is_valid())
        self.assertIn(field, serializer.errors)

    def test_create_valido_preserva_texto_y_defaults(self):
        before = timezone.now()
        serializer = PublicacionCreateSerializer(data=self.payload())
        self.assertTrue(serializer.is_valid(), serializer.errors)
        data = serializer.validated_data
        self.assertEqual(data['titulo'], ' Noticia ')
        self.assertEqual(data['contenido'], ' Texto original ')
        self.assertEqual(data['fuente'], 'Manual')
        self.assertEqual(data['url'], '')
        self.assertLessEqual(before, data['fecha_publicacion'])
        self.assertLessEqual(data['fecha_publicacion'], timezone.now())

    def test_create_obligatorios_faltantes(self):
        for field in ('titulo', 'contenido'):
            with self.subTest(field=field):
                data = self.payload()
                del data[field]
                self.assert_invalid(PublicacionCreateSerializer(data=data), field)

    def test_textos_rechazan_null_vacio_y_espacios(self):
        for field in ('titulo', 'contenido', 'fuente'):
            for value in (None, '', '   ', '\t\n'):
                with self.subTest(field=field, value=value):
                    self.assert_invalid(
                        PublicacionCreateSerializer(data=self.payload(**{field: value})), field,
                    )

    def test_strings_rechazan_conversiones_implicitas(self):
        for field in ('titulo', 'contenido', 'fuente', 'url'):
            for value in (1, 1.5, True, False, [], {}, ['texto'], {'anidado': ['texto']}):
                with self.subTest(field=field, value=value):
                    self.assert_invalid(
                        PublicacionCreateSerializer(data=self.payload(**{field: value})), field,
                    )

    def test_limites_de_longitud(self):
        for field, limit in (('titulo', 255), ('fuente', 100)):
            with self.subTest(field=field):
                valid = PublicacionCreateSerializer(data=self.payload(**{field: 'a' * limit}))
                self.assertTrue(valid.is_valid(), valid.errors)
                self.assert_invalid(
                    PublicacionCreateSerializer(data=self.payload(**{field: 'a' * (limit + 1)})), field,
                )
        for length in (200, 201):
            url = 'https://example.com/' + 'a' * (length - len('https://example.com/'))
            serializer = PublicacionCreateSerializer(data=self.payload(url=url))
            self.assertEqual(serializer.is_valid(), length == 200, serializer.errors)

    def test_url_normalizada_y_opcional(self):
        for value, expected in (('', ''), ('   ', ''),
                                (' https://example.com/noticia \n', 'https://example.com/noticia')):
            with self.subTest(value=value):
                serializer = PublicacionCreateSerializer(data=self.payload(url=value))
                self.assertTrue(serializer.is_valid(), serializer.errors)
                self.assertEqual(serializer.validated_data['url'], expected)
        for value in (None, 'no-es-url', 'https://', 'https://example.com/con espacio'):
            with self.subTest(value=value):
                self.assert_invalid(PublicacionCreateSerializer(data=self.payload(url=value)), 'url')

    def test_fecha_iso8601(self):
        from datetime import datetime, timezone as datetime_timezone

        serializer = PublicacionCreateSerializer(data=self.payload(
            fecha_publicacion='2026-10-08T12:30:00-03:00',
        ))
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['fecha_publicacion'],
                         datetime(2026, 10, 8, 15, 30, tzinfo=datetime_timezone.utc))
        for value in (None, '', '08/10/2026 12:30', '2026-02-30T12:00:00Z', 123, True, [], {}):
            with self.subTest(value=value):
                self.assert_invalid(
                    PublicacionCreateSerializer(data=self.payload(fecha_publicacion=value)),
                    'fecha_publicacion',
                )

    def test_campos_desconocidos(self):
        for serializer_class in (PublicacionCreateSerializer, PublicacionUpdateSerializer):
            with self.subTest(serializer=serializer_class.__name__):
                self.assert_invalid(serializer_class(data=self.payload(extra='valor')), 'extra')

    def test_payload_debe_ser_objeto(self):
        for serializer_class in (PublicacionCreateSerializer, PublicacionUpdateSerializer):
            for value in (None, [], 'texto', 1, True):
                with self.subTest(serializer=serializer_class.__name__, value=value):
                    self.assert_invalid(serializer_class(data=value), 'non_field_errors')

    def test_put_completo_e_incompleto(self):
        serializer = PublicacionUpdateSerializer(data=self.payload())
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data, self.payload())
        for field in ('titulo', 'contenido'):
            data = self.payload()
            del data[field]
            self.assert_invalid(PublicacionUpdateSerializer(data=data), field)
        self.assertFalse(PublicacionUpdateSerializer(data={}).is_valid())

    def test_patch_valido_y_vacio(self):
        for data in ({'titulo': ' Nuevo '}, {'contenido': ' Texto '}, self.payload()):
            serializer = PublicacionUpdateSerializer(data=data, partial=True)
            self.assertTrue(serializer.is_valid(), serializer.errors)
            self.assertEqual(serializer.validated_data, data)
        self.assert_invalid(PublicacionUpdateSerializer(data={}, partial=True), 'non_field_errors')

    def test_update_valida_valores_y_longitud(self):
        for partial in (False, True):
            for field in ('titulo', 'contenido'):
                for value in (None, '', '   ', 1, 1.5, True, False, [], {}):
                    with self.subTest(partial=partial, field=field, value=value):
                        self.assert_invalid(PublicacionUpdateSerializer(
                            data=self.payload(**{field: value}), partial=partial,
                        ), field)
            valid = PublicacionUpdateSerializer(data=self.payload(titulo='a' * 255), partial=partial)
            self.assertTrue(valid.is_valid(), valid.errors)
            self.assert_invalid(PublicacionUpdateSerializer(
                data=self.payload(titulo='a' * 256), partial=partial,
            ), 'titulo')

    def test_update_rechaza_campos_no_editables(self):
        for partial in (False, True):
            for field in ('url', 'hash_origen', 'id_publicacion_api', 'fuente',
                          'fecha_publicacion', 'fecha_captura', 'procesado_ia', 'id_registro'):
                with self.subTest(partial=partial, field=field):
                    self.assert_invalid(PublicacionUpdateSerializer(
                        data=self.payload(**{field: 'valor'}), partial=partial,
                    ), field)

    def test_validacion_sin_escrituras_ni_servicios(self):
        # SimpleTestCase prohibits database access, including attempted writes.
        with patch('core.services.scraper.fetch_and_store_elterritorio') as scraper, \
                patch('core.services.gemini_cliente.procesar_publicaciones_con_ia') as gemini, \
                patch('core.views.analyze_sentiment_lexicon') as lexicon, \
                patch('core.views.compute_probabilistic_sentiment') as probabilistico:
            for serializer in (PublicacionCreateSerializer(data=self.payload()),
                               PublicacionUpdateSerializer(data=self.payload())):
                self.assertTrue(serializer.is_valid(), serializer.errors)
                self.assertEqual(set(serializer.validated_data) & {'hash_origen', 'id_publicacion_api'}, set())
            for service in (scraper, gemini, lexicon, probabilistico):
                service.assert_not_called()

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

    @patch('core.views.procesar_publicaciones_con_ia')
    @patch('core.views.compute_probabilistic_sentiment')
    @patch('core.views.analyze_sentiment_lexicon')
    @patch('core.views.fetch_and_store_elterritorio')
    def test_error_ingesta_detiene_ruta_explicita(self, scraper, lexicon, probabilistico, ia):
        parcial = Publicacion.objects.create(
            hash_origen='parcial', contenido='Guardada antes del error',
            id_registro=self.registro,
        )
        scraper.return_value = {'status': 'ERROR', 'detalle': 'Feed no disponible'}
        response = disparar_ingesta(self.request('/api/publicaciones/ingestar/misiones/'), 'misiones')
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data['status'], 'error')
        self.assertEqual(response.data['mensaje_ingesta'], scraper.return_value)
        scraper.assert_called_once_with('misiones')
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
    def test_update_payloads_validos_conservan_hash_y_no_ejecutan_servicios(self):
        self.autenticar('Administrador')
        ruta = f'/api/publicaciones/{self.publicacion.pk}/actualizar/'
        for metodo, payload in (
            ('put', {'titulo': ' Título PUT ', 'contenido': ' Contenido PUT '}),
            ('patch', {'titulo': 'Título PATCH'}),
            ('patch', {'contenido': 'Contenido PATCH'}),
            ('patch', {'titulo': 'Ambos', 'contenido': 'Ambos campos'}),
        ):
            with self.subTest(metodo=metodo, payload=payload):
                antes = Publicacion.objects.values().get(pk=self.publicacion.pk)
                response = getattr(self.api, metodo)(ruta, payload, format='json')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {
                    'status': 'success',
                    'mensaje': f'Publicación {self.publicacion.pk} actualizada.',
                })
                despues = Publicacion.objects.values().get(pk=self.publicacion.pk)
                self.assertEqual(despues, {**antes, **payload})
                self.assertEqual(despues['hash_origen'], 'roles-prueba')
                for mock in self.mocks.values():
                    mock.assert_not_called()

    def test_update_rechaza_payloads_incompletos_y_vacios(self):
        self.autenticar('Administrador')
        ruta = f'/api/publicaciones/{self.publicacion.pk}/actualizar/'
        for metodo, payload in (
            ('put', {'contenido': 'Nuevo'}), ('put', {'titulo': 'Nuevo'}),
            ('put', {}), ('patch', {}),
        ):
            with self.subTest(metodo=metodo, payload=payload):
                antes = self.estado_datos()
                self.assertEqual(getattr(self.api, metodo)(ruta, payload, format='json').status_code, 400)
                self.assertEqual(self.estado_datos(), antes)

    def test_update_valores_invalidos_no_producen_escrituras_parciales(self):
        self.autenticar('Administrador')
        ruta = f'/api/publicaciones/{self.publicacion.pk}/actualizar/'
        for metodo in ('put', 'patch'):
            for campo in ('titulo', 'contenido'):
                valores = [None, '', '   ', '\t\n', 123, 1.5, True, [], {}]
                if campo == 'titulo':
                    valores.append('a' * 256)
                for valor in valores:
                    with self.subTest(metodo=metodo, campo=campo, valor=valor):
                        antes = self.estado_datos()
                        payload = {'titulo': 'Cambio válido', 'contenido': 'Cambio válido', campo: valor}
                        response = getattr(self.api, metodo)(ruta, payload, format='json')
                        self.assertEqual(response.status_code, 400)
                        self.assertIn(campo, response.data)
                        self.assertEqual(self.estado_datos(), antes)
        for mock in self.mocks.values():
            mock.assert_not_called()

    def test_update_rechaza_campos_no_permitidos_sin_modificar_datos(self):
        self.autenticar('Administrador')
        ruta = f'/api/publicaciones/{self.publicacion.pk}/actualizar/'
        for metodo in ('put', 'patch'):
            for campo in (
                'url', 'hash_origen', 'fuente', 'fecha_captura', 'fecha_publicacion',
                'id', 'pk', 'id_publicacion_api', 'procesado_ia', 'extra',
            ):
                with self.subTest(metodo=metodo, campo=campo):
                    antes = self.estado_datos()
                    response = getattr(self.api, metodo)(ruta, {
                        'titulo': 'Cambio válido', 'contenido': 'Cambio válido', campo: 'Cambio prohibido',
                    }, format='json')
                    self.assertEqual(response.status_code, 400)
                    self.assertIn(campo, response.data)
                    self.assertEqual(self.estado_datos(), antes)
        for mock in self.mocks.values():
            mock.assert_not_called()

    def test_update_publicacion_inexistente_conserva_404(self):
        self.autenticar('Administrador')
        pk = self.publicacion.pk + 1
        self.assertFalse(Publicacion.objects.filter(pk=pk).exists())
        antes = self.estado_datos()
        for metodo in ('put', 'patch'):
            response = getattr(self.api, metodo)(f'/api/publicaciones/{pk}/actualizar/', {
                'titulo': 'Título', 'contenido': 'Texto',
            }, format='json')
            self.assertEqual(response.status_code, 404)
        self.assertEqual(self.estado_datos(), antes)

    def test_update_conserva_permiso_de_edicion_para_ambos_metodos(self):
        ruta = f'/api/publicaciones/{self.publicacion.pk}/actualizar/'
        for rol in (None, 'Usuario', 'Sin rol'):
            self.autenticar(rol)
            for metodo in ('put', 'patch'):
                with self.subTest(rol=rol, metodo=metodo):
                    antes = self.estado_datos()
                    response = getattr(self.api, metodo)(ruta, {
                        'titulo': 'Título', 'contenido': 'Texto',
                    }, format='json')
                    self.assertEqual(response.status_code, 401 if rol is None else 403)
                    self.assertEqual(self.estado_datos(), antes)
        self.usuarios['Sin rol'].user_permissions.add(Permission.objects.get(
            content_type__app_label='core', codename='change_publicacion',
        ))
        self.autenticar('Sin rol')
        for metodo in ('put', 'patch'):
            self.assertEqual(getattr(self.api, metodo)(ruta, {
                'titulo': 'Permiso directo', 'contenido': 'Texto',
            }, format='json').status_code, 200)
        for mock in self.mocks.values():
            mock.assert_not_called()

    def test_update_no_convierte_errores_internos_en_400(self):
        self.autenticar('Administrador')
        antes = self.estado_datos()
        with patch('core.views.Publicacion.save', side_effect=RuntimeError('Error interno')):
            with self.assertRaisesMessage(RuntimeError, 'Error interno'):
                self.api.patch(f'/api/publicaciones/{self.publicacion.pk}/actualizar/', {
                    'titulo': 'Cambio',
                }, format='json')
        self.assertEqual(self.estado_datos(), antes)

    def test_create_invalido_no_tiene_efectos(self):
        self.autenticar('Administrador')
        casos = (
            ({}, ('titulo', 'contenido')),
            ({'titulo': 'Noticia'}, ('contenido',)),
            ({'contenido': 'Texto'}, ('titulo',)),
            ({'titulo': None, 'contenido': 'Texto'}, ('titulo',)),
            ({'titulo': '   ', 'contenido': 'Texto'}, ('titulo',)),
            ({'titulo': 'Noticia', 'contenido': {'texto': ['anidado']}}, ('contenido',)),
            ({'titulo': 'Noticia', 'contenido': 'Texto', 'url': 'no-url'}, ('url',)),
            ({'titulo': 'Noticia', 'contenido': 'Texto', 'fecha_publicacion': 'ayer'}, ('fecha_publicacion',)),
            ({'titulo': 'Noticia', 'contenido': 'Texto', 'extra': 1}, ('extra',)),
            ([], ('non_field_errors',)),
            (None, None),
            ('texto', ('non_field_errors',)),
            (True, ('non_field_errors',)),
        )
        for payload, fields in casos:
            with self.subTest(payload=payload):
                antes = self.estado_datos()
                # Send literal JSON null; APIClient treats data=None as no body.
                response = self.api.generic(
                    'POST', '/api/publicaciones/crear/', json.dumps(payload),
                    content_type='application/json',
                )
                self.assertEqual(response.status_code, 400)
                for field in fields or ():
                    self.assertIn(field, response.data)
                self.assertEqual(self.estado_datos(), antes)
                for mock in self.mocks.values():
                    mock.assert_not_called()

    def test_create_manual_conserva_defaults_fecha_y_sentimiento(self):
        self.autenticar('Administrador')
        antes = timezone.now()
        response = self.api.post('/api/publicaciones/crear/', {
            'titulo': ' Título original ', 'contenido': ' Contenido original ',
        }, format='json')
        self.assertEqual(response.status_code, 201)
        publicacion = Publicacion.objects.get(pk=response.data['id_publicacion_api'])
        self.assertEqual(publicacion.titulo, ' Título original ')
        self.assertEqual(publicacion.contenido, ' Contenido original ')
        self.assertEqual(publicacion.fuente, 'Manual')
        self.assertEqual(publicacion.url, '')
        self.assertEqual(publicacion.hash_origen, hashlib.sha256(b' T\xc3\xadtulo original ').hexdigest())
        self.assertLessEqual(antes, publicacion.fecha_captura)
        self.assertLessEqual(publicacion.fecha_captura, timezone.now())
        self.assertTrue(publicacion.procesado_ia)
        sentimiento = Sentimiento.objects.get(id_publicacion_api=publicacion)
        self.assertEqual(response.data['sentimiento'], {
            'id_sentimiento': sentimiento.pk, 'polaridad': 0.5, 'confianza': 0.8,
        })
        self.mocks['analyze_sentiment_lexicon'].assert_called_once_with(' Título original   Contenido original ')
        self.mocks['compute_probabilistic_sentiment'].assert_called_once_with([
            {'message': ' Título original   Contenido original '},
        ])
        self.mocks['fetch_and_store_elterritorio'].assert_not_called()
        self.mocks['procesar_publicaciones_con_ia'].assert_not_called()

    def test_create_manual_normaliza_url_y_asigna_fecha(self):
        from datetime import datetime, timezone as datetime_timezone

        self.autenticar('Administrador')
        response = self.api.post('/api/publicaciones/crear/', {
            'titulo': 'Con URL', 'contenido': 'Texto', 'fuente': 'Fuente explícita',
            'url': ' https://example.com/noticia \n',
            'fecha_publicacion': '2026-10-08T12:30:00-03:00',
        }, format='json')
        self.assertEqual(response.status_code, 201)
        publicacion = Publicacion.objects.get(pk=response.data['id_publicacion_api'])
        self.assertEqual(publicacion.url, 'https://example.com/noticia')
        self.assertEqual(publicacion.hash_origen, hashlib.sha256(publicacion.url.encode('utf-8')).hexdigest())
        self.assertEqual(publicacion.fuente, 'Fuente explícita')
        self.assertEqual(publicacion.fecha_captura, datetime(2026, 10, 8, 15, 30, tzinfo=datetime_timezone.utc))
        self.mocks['fetch_and_store_elterritorio'].assert_not_called()
        self.mocks['procesar_publicaciones_con_ia'].assert_not_called()

    def test_permisos_ingesta_no_autorizan_create(self):
        usuario = self.usuarios['Sin rol']
        usuario.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='core', codename__in=('ejecutar_scraping', 'procesar_ia'),
        ))
        self.autenticar('Sin rol')
        antes = self.estado_datos()
        for payload in ({}, {'titulo': 'Noticia', 'contenido': 'Texto'}):
            response = self.api.post('/api/publicaciones/crear/', payload, format='json')
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.estado_datos(), antes)
        for mock in self.mocks.values():
            mock.assert_not_called()
        self.assertEqual(self.api.post('/api/publicaciones/ingestar/misiones/', {}, format='json').status_code, 200)
        self.mocks['fetch_and_store_elterritorio'].assert_called_once_with('misiones')
        self.mocks['procesar_publicaciones_con_ia'].assert_called_once_with(batch_size=10)

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
                self.assertEqual(self.api.post('/api/publicaciones/crear/', {}, format='json').status_code, 400)
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
        self.assertEqual(self.api.post('/api/publicaciones/crear/', {}, format='json').status_code, 400)
        self.assertEqual(self.client.post('/procesar-ia/').status_code, 403)
        self.mocks['fetch_and_store_elterritorio'].assert_not_called()
        self.mocks['procesar_publicaciones_con_ia'].assert_not_called()
        self.mocks['analyze_sentiment_lexicon'].assert_called_once()
        self.mocks['compute_probabilistic_sentiment'].assert_called_once()

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


class ScraperAlternativoTestCase(TestCase):
    @patch('core.scrapers.noticias.Publicacion.objects.get_or_create')
    @patch('core.scrapers.noticias.urllib.request.urlopen')
    def test_error_lectura_se_propaga_sin_intentar_guardar(self, urlopen, guardar):
        error = OSError('Lectura del feed interrumpida')
        urlopen.return_value.__enter__.return_value.read.side_effect = error
        with patch('builtins.print') as salida:
            with self.assertRaises(OSError) as contexto:
                fetch_elterritorio_news()
        self.assertIs(contexto.exception, error)
        guardar.assert_not_called()
        salida.assert_not_called()

    @patch('core.scrapers.noticias.Publicacion.objects.get_or_create')
    @patch('core.scrapers.noticias.urllib.request.urlopen')
    def test_error_persistencia_se_propaga_sin_anunciar_exito(self, urlopen, guardar):
        xml = b'''<rss><channel><item>
            <title>Noticia del feed</title>
            <link>https://www.elterritorio.com.ar/noticias/918312-noticia</link>
            <description>Contenido del feed</description>
        </item></channel></rss>'''
        urlopen.return_value.__enter__.return_value.read.return_value = xml
        error = RuntimeError('Fallo al guardar la noticia')
        guardar.side_effect = error
        with patch('builtins.print') as salida:
            with self.assertRaises(RuntimeError) as contexto:
                fetch_elterritorio_news()
        self.assertIs(contexto.exception, error)
        guardar.assert_called_once()
        self.assertEqual(guardar.call_args.kwargs['id_publicacion_api'], 918312)
        salida.assert_not_called()

    @patch('core.scrapers.noticias.urllib.request.urlopen')
    def test_fallos_de_red_no_generan_publicaciones(self, urlopen):
        for error in (URLError('Feed no disponible'), TimeoutError('Tiempo agotado')):
            with self.subTest(error=type(error).__name__):
                urlopen.side_effect = error
                with patch('builtins.print') as salida:
                    with self.assertRaises(type(error)) as contexto:
                        fetch_elterritorio_news()
                self.assertIs(contexto.exception, error)
                self.assertFalse(Publicacion.objects.exists())
                salida.assert_not_called()

    @patch('core.scrapers.noticias.urllib.request.urlopen')
    def test_xml_invalido_no_genera_publicaciones(self, urlopen):
        urlopen.return_value.__enter__.return_value.read.return_value = b'<rss>'
        with patch('builtins.print') as salida:
            with self.assertRaises(ET.ParseError):
                fetch_elterritorio_news()
        self.assertFalse(Publicacion.objects.exists())
        salida.assert_not_called()

    @patch('core.scrapers.noticias.urllib.request.urlopen')
    def test_rss_vacio_valido_devuelve_lista_vacia(self, urlopen):
        urlopen.return_value.__enter__.return_value.read.return_value = b'<rss><channel /></rss>'
        with patch('builtins.print'):
            self.assertEqual(fetch_elterritorio_news(), [])
        self.assertFalse(Publicacion.objects.exists())

    @patch('core.scrapers.noticias.urllib.request.urlopen')
    def test_extrae_y_persiste_noticia_del_feed(self, urlopen):
        enlace = 'https://www.elterritorio.com.ar/noticias/2026/10/07/918312-noticia'
        xml = f'''<rss><channel><item>
            <title> Noticia del feed </title><link>{enlace}</link>
            <description>&lt;p&gt;Contenido del feed&lt;/p&gt;</description>
        </item></channel></rss>'''
        urlopen.return_value.__enter__.return_value.read.return_value = xml.encode('utf-8')
        with patch('builtins.print'):
            articulos = fetch_elterritorio_news(category='misiones', limit=1)
        hash_origen = hashlib.sha256(enlace.encode('utf-8')).hexdigest()
        self.assertEqual(articulos, [{
            'id_noticia': 918312, 'hash_origen': hash_origen,
            'title': 'Noticia del feed', 'link': enlace,
            'summary': 'Contenido del feed', 'source': 'El Territorio',
        }])
        self.assertEqual(Publicacion.objects.count(), 1)
        publicacion = Publicacion.objects.get(pk=918312)
        self.assertEqual(publicacion.hash_origen, hash_origen)
        self.assertEqual(publicacion.titulo, 'Noticia del feed')
        self.assertEqual(publicacion.contenido, 'Contenido del feed')
        self.assertEqual(publicacion.url, enlace)
        self.assertEqual(publicacion.fuente, 'El Territorio')
        self.assertFalse(publicacion.procesado_ia)


class EjecutarScraperCommandTestCase(TestCase):
    @patch('core.management.commands.ejecutar_scraper.fetch_elterritorio_news')
    def test_error_preserva_causa_y_no_emite_exito(self, scraper):
        error = URLError('Feed no disponible')
        scraper.side_effect = error
        salida = StringIO()
        with self.assertRaisesMessage(CommandError, 'Feed no disponible') as contexto:
            call_command('ejecutar_scraper', category='policiales', limit=2, stdout=salida)
        self.assertIs(contexto.exception.__cause__, error)
        scraper.assert_called_once_with(category='policiales', limit=2)
        self.assertNotIn('Ingesta finalizada correctamente', salida.getvalue())
        self.assertNotIn('[✔]', salida.getvalue())

    @patch('core.management.commands.ejecutar_scraper.fetch_elterritorio_news', return_value=[])
    def test_lista_vacia_es_finalizacion_valida(self, scraper):
        salida = StringIO()
        call_command('ejecutar_scraper', stdout=salida)
        self.assertIn('Ingesta finalizada correctamente. Se procesaron 0 artículos.', salida.getvalue())
        scraper.assert_called_once_with(category='misiones', limit=5)


class RunPipelineCommandTestCase(TestCase):
    def setUp(self):
        ingesta = patch('core.management.commands.run_pipeline.fetch_and_store_elterritorio')
        posterior = patch(
            'core.management.commands.run_pipeline.procesar_publicaciones_con_ia',
            return_value='Procesamiento completado',
        )
        self.ingesta = ingesta.start()
        self.addCleanup(ingesta.stop)
        self.posterior = posterior.start()
        self.addCleanup(posterior.stop)
        self.salida = StringIO()

    def assert_sin_procesamiento_ni_exito(self):
        self.posterior.assert_not_called()
        texto = self.salida.getvalue()
        for mensaje in ('Ingesta finalizada:', 'Ejecutando Análisis', 'IA finalizada:',
                        'Pipeline completado exitosamente.'):
            self.assertNotIn(mensaje, texto)

    def test_exito_final_se_anuncia_despues_del_procesamiento_posterior(self):
        self.ingesta.return_value = {'status': 'EXITO', 'capturados': 1, 'registro_id': 1}
        mensaje = 'Pipeline completado exitosamente.'

        def procesar(batch_size):
            self.assertEqual(batch_size, 10)
            self.assertNotIn(mensaje, self.salida.getvalue())
            return 'Procesamiento completado'

        self.posterior.side_effect = procesar
        call_command('run_pipeline', stdout=self.salida)
        self.posterior.assert_called_once_with(batch_size=10)
        self.assertIn(mensaje, self.salida.getvalue())

        self.salida = StringIO()
        error = RuntimeError('Fallo del procesamiento posterior')
        self.posterior.side_effect = error
        with self.assertRaises(RuntimeError) as contexto:
            call_command('run_pipeline', stdout=self.salida)
        self.assertIs(contexto.exception, error)
        self.assertNotIn(mensaje, self.salida.getvalue())
        self.assertNotIn('IA finalizada:', self.salida.getvalue())

    def test_error_ingesta_detiene_pipeline_sin_exito(self):
        self.ingesta.return_value = {'status': 'ERROR', 'detalle': 'Feed no disponible'}
        with self.assertRaisesMessage(CommandError, 'Feed no disponible'):
            call_command('run_pipeline', stdout=self.salida)
        self.assert_sin_procesamiento_ni_exito()

    def test_excepcion_ingesta_preserva_causa_y_detiene_pipeline(self):
        error = RuntimeError('Fallo técnico de ingesta')
        self.ingesta.side_effect = error
        with self.assertRaisesMessage(CommandError, 'Fallo técnico de ingesta') as contexto:
            call_command('run_pipeline', stdout=self.salida)
        self.assertIs(contexto.exception.__cause__, error)
        self.assert_sin_procesamiento_ni_exito()

    def test_estados_inesperados_detienen_pipeline(self):
        for resultado in ({}, {'status': 'EN_PROCESO'}, {'status': None}, {'status': 'exito'}):
            with self.subTest(resultado=resultado):
                self.ingesta.return_value = resultado
                with self.assertRaises(CommandError):
                    call_command('run_pipeline', stdout=self.salida)
                self.assert_sin_procesamiento_ni_exito()

    def test_resultados_invalidos_detienen_pipeline(self):
        for resultado in (None, [], 'EXITO', 0, True):
            with self.subTest(resultado=resultado):
                self.ingesta.return_value = resultado
                with self.assertRaisesMessage(CommandError, 'se esperaba un diccionario'):
                    call_command('run_pipeline', stdout=self.salida)
                self.assert_sin_procesamiento_ni_exito()

    def test_exito_con_cero_y_multiples_capturas_continua(self):
        for capturados in (0, 3):
            with self.subTest(capturados=capturados):
                self.ingesta.reset_mock()
                self.posterior.reset_mock()
                salida = StringIO()
                self.ingesta.return_value = {
                    'status': 'EXITO', 'capturados': capturados, 'registro_id': 1,
                }
                call_command('run_pipeline', categoria='policiales', stdout=salida)
                self.ingesta.assert_called_once_with('policiales')
                self.posterior.assert_called_once_with(batch_size=10)
                self.assertIn('Ingesta finalizada:', salida.getvalue())
                self.assertIn('Pipeline completado exitosamente.', salida.getvalue())


class PublicacionDuplicadosTestCase(TestCase):
    def setUp(self):
        from rest_framework.test import APIClient

        self.api = APIClient()
        self.usuario = get_user_model().objects.create_superuser(username='duplicados')
        self.api.force_authenticate(self.usuario)
        self.servicios = {}
        for nombre, resultado in (
            ('analyze_sentiment_lexicon', 0.5),
            ('compute_probabilistic_sentiment', {'confidence_score': 0.8}),
            ('fetch_and_store_elterritorio', None),
            ('procesar_publicaciones_con_ia', None),
        ):
            parche = patch('core.views.' + nombre, return_value=resultado)
            self.servicios[nombre] = parche.start()
            self.addCleanup(parche.stop)

    def crear(self, titulo='Original', url=''):
        return Publicacion.objects.create(
            hash_origen=hashlib.sha256((url or titulo).encode('utf-8')).hexdigest(),
            titulo=titulo, contenido='Original', url=url,
        )

    def solicitar(self, **datos):
        return self.api.post('/api/publicaciones/crear/', {
            'titulo': 'Original', 'contenido': 'Otro contenido', **datos,
        }, format='json')

    def comprobar_duplicado(self, respuesta, existente):
        self.assertEqual(respuesta.status_code, 409)
        self.assertEqual(respuesta.data, {
            'status': 'error', 'codigo': 'publicacion_duplicada',
            'mensaje': 'Ya existe una publicación con esta identidad.',
            'id_publicacion_api': existente.pk,
        })
        self.assertEqual(Publicacion.objects.count(), 1)
        self.assertFalse(Sentimiento.objects.exists())
        for servicio in self.servicios.values():
            servicio.assert_not_called()

    def test_misma_url_con_titulo_y_contenido_diferentes(self):
        existente = self.crear(url='https://example.com/noticia')
        self.comprobar_duplicado(self.solicitar(titulo='Otra', url=existente.url), existente)

    def test_mismo_titulo_sin_url(self):
        existente = self.crear()
        self.comprobar_duplicado(self.solicitar(), existente)

    def test_url_con_espacios_externos(self):
        existente = self.crear(url='https://example.com/noticia')
        self.comprobar_duplicado(self.solicitar(url=' ' + existente.url + '\n'), existente)

    def test_duplicado_de_publicacion_rss(self):
        existente = self.crear(url='https://example.com/rss')
        registro = RegistroDatos.objects.create(
            fuentes_api='El Territorio', fecha_ejecucion=timezone.now(), estado='EXITO', lenguaje='es',
        )
        existente.id_registro = registro
        existente.fuente = 'El Territorio (Misiones)'
        existente.save()
        self.comprobar_duplicado(self.solicitar(url=existente.url), existente)
        self.assertEqual(RegistroDatos.objects.count(), 1)

    def test_colision_real_despues_de_consulta_sin_resultados(self):
        existente = self.crear()
        consulta_real = Publicacion.objects.filter(hash_origen=existente.hash_origen)
        with patch('core.views.Publicacion.objects.filter') as consultar:
            consultar.return_value.first.side_effect = [None, consulta_real.first()]
            self.comprobar_duplicado(self.solicitar(), existente)
            self.assertEqual(consultar.call_args_list, [
                call(hash_origen=existente.hash_origen),
                call(hash_origen=existente.hash_origen),
            ])
        # La conexión sigue utilizable después del rollback del savepoint.
        self.assertEqual(Publicacion.objects.get(pk=existente.pk).hash_origen, existente.hash_origen)

    def test_fallo_introspeccion_en_colision_real_se_propaga(self):
        existente = self.crear()
        error = OperationalError('Fallo de introspección PostgreSQL')
        with patch('core.views.Publicacion.objects.filter') as consultar, \
                patch('core.views.connection.introspection.get_constraints', side_effect=error) as introspeccion:
            consultar.return_value.first.return_value = None
            with self.assertRaises(OperationalError) as contexto:
                self.solicitar()
            consultar.assert_called_once_with(hash_origen=existente.hash_origen)
            introspeccion.assert_called_once()
            self.assertEqual(introspeccion.call_args.args[1], Publicacion._meta.db_table)
        self.assertIs(contexto.exception, error)
        # El fallo de introspección ocurre al manejar una violación real de unicidad.
        colision = contexto.exception.__context__
        self.assertIsInstance(colision, IntegrityError)
        self.assertEqual(colision.__cause__.diag.sqlstate, '23505')
        self.assertEqual(colision.__cause__.diag.table_name, Publicacion._meta.db_table)
        self.assertEqual(Publicacion.objects.get().pk, existente.pk)
        self.assertFalse(Sentimiento.objects.exists())
        for servicio in self.servicios.values():
            servicio.assert_not_called()

    def test_error_de_unicidad_de_pk_se_propaga(self):
        existente = self.crear()
        insertar = Publicacion.objects.create

        def colision_pk(**datos):
            return insertar(id_publicacion_api=existente.pk, **datos)

        with patch('core.views.Publicacion.objects.create', side_effect=colision_pk):
            with self.assertRaises(IntegrityError) as contexto:
                self.solicitar(titulo='Identidad distinta')
        self.assertEqual(contexto.exception.__cause__.diag.sqlstate, '23505')
        self.assertEqual(Publicacion.objects.count(), 1)
        for servicio in self.servicios.values():
            servicio.assert_not_called()

    def test_error_not_null_se_propaga(self):
        insertar = Publicacion.objects.create

        def contenido_nulo(**datos):
            datos['contenido'] = None
            return insertar(**datos)

        with patch('core.views.Publicacion.objects.create', side_effect=contenido_nulo):
            with self.assertRaises(IntegrityError) as contexto:
                self.solicitar()
        self.assertEqual(contexto.exception.__cause__.diag.sqlstate, '23502')
        self.assertFalse(Publicacion.objects.exists())
        for servicio in self.servicios.values():
            servicio.assert_not_called()

    def test_error_sin_diagnostico_se_propaga(self):
        error = IntegrityError('Error sin diagnóstico del driver')
        with patch('core.views.Publicacion.objects.create', side_effect=error):
            with self.assertRaises(IntegrityError) as contexto:
                self.solicitar()
        self.assertIs(contexto.exception, error)

    def test_colision_confirmada_sin_id_recuperable(self):
        existente = self.crear()
        with patch('core.views.Publicacion.objects.filter') as consultar:
            consultar.return_value.first.return_value = None
            respuesta = self.solicitar()
            self.assertEqual(consultar.call_args_list, [
                call(hash_origen=existente.hash_origen),
                call(hash_origen=existente.hash_origen),
            ])
        self.assertEqual(respuesta.status_code, 409)
        self.assertEqual(respuesta.data, {
            'status': 'error', 'codigo': 'publicacion_duplicada',
            'mensaje': 'Ya existe una publicación con esta identidad.',
        })
        self.assertEqual(Publicacion.objects.get().pk, existente.pk)
        for servicio in self.servicios.values():
            servicio.assert_not_called()

    def test_edicion_conserva_identidad_original_basada_en_titulo(self):
        existente = self.crear(titulo='Antes')
        hash_original = existente.hash_origen
        respuesta = self.api.patch(f'/api/publicaciones/{existente.pk}/actualizar/', {
            'titulo': 'Después',
        }, format='json')
        self.assertEqual(respuesta.status_code, 200)
        existente.refresh_from_db()
        self.assertEqual(existente.hash_origen, hash_original)
        self.comprobar_duplicado(self.solicitar(titulo='Antes'), existente)
        # El nuevo título tiene otra identidad: puede coexistir con la fila editada.
        respuesta = self.solicitar(titulo='Después')
        self.assertEqual(respuesta.status_code, 201)
        self.assertEqual(Publicacion.objects.filter(titulo='Después').count(), 2)


class PublicacionConcurrenciaTestCase(TransactionTestCase):
    def test_dos_conexiones_crean_una_sola_publicacion(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from rest_framework.test import APIClient

        usuario = get_user_model().objects.create_superuser(username='concurrencia')
        barrera = Barrier(2, timeout=15)
        insertar = Publicacion.objects.create

        def insertar_sincronizado(**datos):
            # Ambas solicitudes ya completaron su consulta previa sin resultados.
            barrera.wait()
            return insertar(**datos)

        def solicitar():
            try:
                api = APIClient()
                api.force_authenticate(get_user_model().objects.get(pk=usuario.pk))
                return api.post('/api/publicaciones/crear/', {
                    'titulo': 'Concurrente', 'contenido': 'Texto',
                    'url': 'https://example.com/concurrente',
                }, format='json')
            finally:
                connections.close_all()

        with patch('core.views.Publicacion.objects.create', side_effect=insertar_sincronizado), \
                patch('core.views.analyze_sentiment_lexicon', return_value=0.5) as lexicon, \
                patch('core.views.compute_probabilistic_sentiment', return_value={'confidence_score': 0.8}) as probabilistico, \
                patch('core.views.fetch_and_store_elterritorio') as rss, \
                patch('core.views.procesar_publicaciones_con_ia') as gemini:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futuros = [executor.submit(solicitar) for _ in range(2)]
                respuestas = [futuro.result(timeout=30) for futuro in futuros]
            self.assertEqual(sorted(r.status_code for r in respuestas), [201, 409])
            duplicada = next(r for r in respuestas if r.status_code == 409)
            self.assertEqual(duplicada.data['id_publicacion_api'], Publicacion.objects.get().pk)
            self.assertEqual(duplicada.data['codigo'], 'publicacion_duplicada')
            self.assertEqual(Publicacion.objects.count(), 1)
            self.assertEqual(Sentimiento.objects.count(), 1)
            lexicon.assert_called_once()
            probabilistico.assert_called_once()
            rss.assert_not_called()
            gemini.assert_not_called()
