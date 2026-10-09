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


class LoginIdentificadorTestCase(TestCase):
    def setUp(self):
        from rest_framework.test import APIClient
        self.api = APIClient()
        self.password = '  clave de prueba  '
        self.usuario = get_user_model().objects.create_user(
            username='cuenta@local', email='Cuenta@example.test', password=self.password,
        )

    def comprobar_exito(self, identificador):
        self.client.logout()
        respuesta = self.client.post('/login/', {
            'username': identificador, 'password': self.password,
        })
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.usuario.pk)
        respuesta = self.api.post('/api/auth/login/', {
            'username': identificador, 'password': self.password,
        }, format='json')
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(set(respuesta.data), {'access', 'refresh'})
        self.api.credentials(HTTP_AUTHORIZATION='Bearer ' + respuesta.data['access'])
        perfil = self.api.get('/api/auth/me/')
        self.assertEqual(perfil.status_code, 200)
        self.assertEqual(perfil.data['id'], self.usuario.pk)
        self.api.credentials()

    def comprobar_rechazo(self, identificador, password=None):
        from core.services.autenticacion import ERROR_CREDENCIALES
        self.client.logout()
        datos = {'username': identificador, 'password': self.password if password is None else password}
        respuesta = self.client.post('/login/', datos)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context['login_error'], ERROR_CREDENCIALES)
        self.assertNotIn('_auth_user_id', self.client.session)
        respuesta = self.api.post('/api/auth/login/', datos, format='json')
        self.assertEqual(respuesta.status_code, 401)
        self.assertEqual(str(respuesta.data['detail']), ERROR_CREDENCIALES)
        self.assertNotIn('access', respuesta.data)

    def test_username_email_case_y_espacios(self):
        for identificador in ('cuenta@local', ' Cuenta@example.test ', 'CUENTA@EXAMPLE.TEST'):
            with self.subTest(identificador=identificador):
                self.comprobar_exito(identificador)
        self.comprobar_rechazo('CUENTA@LOCAL')

    def test_password_no_se_recorta(self):
        self.comprobar_rechazo(self.usuario.username, self.password.strip())
        self.usuario.set_password('   ')
        self.usuario.save(update_fields=['password'])
        self.password = '   '
        self.comprobar_exito(self.usuario.email)

    def test_username_sin_arroba_y_email_vacio(self):
        self.usuario.username = 'cuenta_normal'
        self.usuario.email = ''
        self.usuario.save(update_fields=['username', 'email'])
        get_user_model().objects.create_user(username='otra_sin_email', email='')
        self.comprobar_exito(' cuenta_normal ')

    def test_password_inutilizable(self):
        self.usuario.set_unusable_password()
        self.usuario.save(update_fields=['password'])
        self.comprobar_rechazo(self.usuario.username)
        self.comprobar_rechazo(self.usuario.email)

    def test_inexistente_inactivo_y_password_incorrecto(self):
        self.comprobar_rechazo('inexistente')
        self.comprobar_rechazo(self.usuario.email, 'incorrecta')
        self.usuario.is_active = False
        self.usuario.save(update_fields=['is_active'])
        self.comprobar_rechazo(self.usuario.username)
        self.comprobar_rechazo(self.usuario.email)

    def test_duplicados_incluyen_inactivos_y_no_eligen_por_password(self):
        otro = get_user_model().objects.create_user(
            username='otra', email=self.usuario.email, password='distinta', is_active=False,
        )
        self.comprobar_rechazo(self.usuario.email)
        otro.email = self.usuario.email.upper()
        otro.save(update_fields=['email'])
        self.comprobar_rechazo(self.usuario.email)

    def test_colision_email_username_y_misma_cuenta(self):
        get_user_model().objects.create_user(username=self.usuario.email, password='distinta')
        self.comprobar_rechazo(self.usuario.email)
        self.usuario.email = self.usuario.username
        self.usuario.save(update_fields=['email'])
        self.comprobar_exito(self.usuario.username)

    def test_tipos_invalidos_y_campos_ausentes(self):
        from core.services.autenticacion import autenticar_identificador
        for valor in (123, 1.5, True, [], {}, None):
            self.assertIsNone(autenticar_identificador(None, valor, self.password))
            for campo in ('username', 'password'):
                datos = {'username': self.usuario.username, 'password': self.password, campo: valor}
                self.assertEqual(self.api.post('/api/auth/login/', datos, format='json').status_code, 400)
        for datos in ({}, {'username': self.usuario.username}, {'password': self.password}):
            self.assertEqual(self.api.post('/api/auth/login/', datos, format='json').status_code, 400)

    def test_identificador_vacio_o_solo_espacios(self):
        from core.services.autenticacion import ERROR_CREDENCIALES
        for identificador in ('', '   ', '\t\n '):
            with self.subTest(identificador=repr(identificador)):
                self.client.logout()
                datos = {'username': identificador, 'password': self.password}
                with patch('core.views.login') as iniciar_sesion, patch(
                    'core.serializers.LoginTokenObtainPairSerializer.get_token'
                ) as emitir:
                    respuesta = self.client.post('/login/', datos)
                    self.assertEqual(respuesta.status_code, 200)
                    self.assertEqual(respuesta.context['login_error'], ERROR_CREDENCIALES)
                    self.assertNotIn('_auth_user_id', self.client.session)
                    respuesta = self.api.post('/api/auth/login/', datos, format='json')
                    self.assertEqual(respuesta.status_code, 400)
                    self.assertEqual(set(respuesta.data), {'username'})
                    self.assertEqual(respuesta.data['username'][0].code, 'blank')
                    iniciar_sesion.assert_not_called()
                    emitir.assert_not_called()

    def test_identidad_se_comprueba_antes_de_login_y_tokens(self):
        otro = get_user_model().objects.create_user(username='otro')
        with patch('core.services.autenticacion.authenticate', return_value=otro), patch(
            'core.serializers.LoginTokenObtainPairSerializer.get_token'
        ) as emitir, patch('core.views.login') as iniciar_sesion:
            self.comprobar_rechazo(self.usuario.username)
            iniciar_sesion.assert_not_called()
            emitir.assert_not_called()

    def test_navegacion_anonima_y_autenticada(self):
        from django.shortcuts import render

        def paginas():
            portada = self.client.get('/')
            # Categorías y Litoral ocultan los bloques nav/footer de base.html.
            return portada, render(portada.wsgi_request, 'base.html')

        for respuesta in paginas():
            self.assertContains(respuesta, '<span>Ingresar</span>', html=True)
            self.assertContains(respuesta, 'Iniciar sesión')
            self.assertNotContains(respuesta, 'Cerrar sesión')
        respuesta = self.client.post('/login/', {
            'username': self.usuario.email, 'password': self.password,
        }, follow=True)
        self.assertEqual(respuesta.redirect_chain, [('/', 302)])
        for respuesta in paginas():
            self.assertContains(respuesta, 'Hola, ' + self.usuario.username)
            self.assertContains(respuesta, 'Cerrar sesión')
            self.assertNotContains(respuesta, '<span>Ingresar</span>', html=True)
            self.assertNotContains(respuesta, '>Iniciar sesión</a>')

    def test_error_anonimo_conserva_identificador_sin_password(self):
        identificador = '  CUENTA@EXAMPLE.TEST  '
        password_incorrecto = 'password-no-devolver'
        respuesta = self.client.post('/login/', {
            'username': identificador, 'password': password_incorrecto,
        })
        self.assertEqual(respuesta.status_code, 200)
        self.assertNotIn('Location', respuesta)
        self.assertEqual(respuesta.context['login_identifier'], identificador.strip())
        self.assertTrue(respuesta.context['open_login_modal'])
        self.assertContains(respuesta, 'value="CUENTA@EXAMPLE.TEST"')
        self.assertContains(respuesta, 'Usuario o contraseña incorrectos.')
        self.assertContains(respuesta, '<p class="form-msg" role="alert" data-auth-error-message>Usuario o contraseña incorrectos.</p>', html=True)
        self.assertNotContains(respuesta, password_incorrecto)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_autenticado_redirige_sin_revalidar_credenciales(self):
        self.client.force_login(self.usuario)
        with patch('core.views.autenticar_identificador') as autenticar:
            for metodo in ('get', 'post'):
                respuesta = getattr(self.client, metodo)('/login/', {
                    'username': self.usuario.email, 'password': 'incorrecta',
                })
                self.assertRedirects(respuesta, '/', fetch_redirect_response=False)
                self.assertEqual(int(self.client.session['_auth_user_id']), self.usuario.pk)
            autenticar.assert_not_called()

    def test_backend_recibe_username_canonico_y_password_intacto(self):
        from core.services.autenticacion import autenticar_identificador
        with patch('core.services.autenticacion.authenticate', return_value=self.usuario) as backend:
            self.assertEqual(autenticar_identificador(None, self.usuario.email.upper(), self.password), self.usuario)
            backend.assert_called_once_with(None, username=self.usuario.username, password=self.password)

    def test_roles_grupos_historicos_y_permisos_se_preservan(self):
        for rol in ('Usuario', 'Administrador', 'Lector'):
            self.usuario.groups.add(Group.objects.create(name=rol))
        permiso = Permission.objects.get(content_type__app_label='core', codename='view_publicacion')
        self.usuario.user_permissions.add(permiso)
        for identificador in (self.usuario.username, self.usuario.email):
            self.comprobar_exito(identificador)
            respuesta = self.api.post('/api/auth/login/', {
                'username': identificador, 'password': self.password,
            }, format='json')
            self.api.credentials(HTTP_AUTHORIZATION='Bearer ' + respuesta.data['access'])
            self.assertEqual(self.api.get('/api/auth/me/').data['roles'], ['ADMINISTRADOR', 'USUARIO'])
            self.api.credentials()
        self.usuario.refresh_from_db()
        self.assertEqual(set(self.usuario.groups.values_list('name', flat=True)), {'Usuario', 'Administrador', 'Lector'})
        self.assertTrue(self.usuario.user_permissions.filter(pk=permiso.pk).exists())
        self.assertTrue(self.usuario.has_perm('core.view_publicacion'))


class JWTRevocacionTestCase(TestCase):
    def setUp(self):
        from rest_framework.test import APIClient
        self.api = APIClient()
        self.usuario = get_user_model().objects.create_user(
            username='jwt_prueba', email='jwt@example.test', password='clave prueba',
        )
        self.par = self.obtener_par(self.usuario.username)
        self.api.credentials(HTTP_AUTHORIZATION='Bearer ' + self.par['access'])

    def obtener_par(self, identificador):
        respuesta = self.api.post('/api/auth/login/', {
            'username': identificador, 'password': 'clave prueba',
        }, format='json')
        self.assertEqual(respuesta.status_code, 200)
        return respuesta.data

    def refrescar(self, token):
        return self.api.post('/api/auth/refresh/', {'refresh': token}, format='json')

    def cerrar(self, token):
        return self.api.post('/api/auth/logout/', {'refresh': token}, format='json')

    def test_rutas_y_nombres_publicos_conservados(self):
        from django.urls import resolve, reverse
        from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
        for nombre, ruta, vista in (
            ('token_obtain_pair', '/api/auth/login/', TokenObtainPairView),
            ('token_refresh', '/api/auth/refresh/', TokenRefreshView),
        ):
            self.assertEqual(reverse(nombre), ruta)
            self.assertEqual(resolve(ruta).func.view_class, vista)
        self.assertEqual(reverse('jwt_logout'), '/api/auth/logout/')

    def test_rotacion_por_username_y_email_revoca_refresh_anterior(self):
        from rest_framework_simplejwt.tokens import RefreshToken
        from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
        for identificador in (self.usuario.username, self.usuario.email.upper()):
            par = self.obtener_par(identificador)
            anterior = RefreshToken(par['refresh'])
            self.assertTrue(OutstandingToken.objects.filter(jti=anterior['jti']).exists())
            respuesta = self.refrescar(par['refresh'])
            self.assertEqual(respuesta.status_code, 200)
            self.assertEqual(set(respuesta.data), {'access', 'refresh'})
            nuevo = RefreshToken(respuesta.data['refresh'])
            self.assertNotEqual(nuevo['jti'], anterior['jti'])
            self.assertTrue(BlacklistedToken.objects.filter(token__jti=anterior['jti']).exists())
            self.assertTrue(OutstandingToken.objects.filter(jti=nuevo['jti']).exists())
            self.assertEqual(self.refrescar(par['refresh']).status_code, 401)
            self.assertEqual(self.refrescar(respuesta.data['refresh']).status_code, 200)

    def test_logout_propio_revoca_refresh_y_access_sigue_valido(self):
        self.assertEqual(self.cerrar(self.par['refresh']).status_code, 204)
        self.assertEqual(self.refrescar(self.par['refresh']).status_code, 401)
        self.assertEqual(self.api.get('/api/auth/me/').status_code, 200)
        segunda = self.cerrar(self.par['refresh'])
        self.assertEqual(segunda.status_code, 400)
        self.assertEqual(str(segunda.data['refresh'][0]), 'Refresh token inválido.')

    def test_refresh_ajeno_no_se_revoca(self):
        from rest_framework_simplejwt.tokens import RefreshToken
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
        otro = get_user_model().objects.create_user(username='jwt_otro')
        token = RefreshToken.for_user(otro)
        self.assertEqual(self.cerrar(str(token)).status_code, 403)
        self.assertFalse(BlacklistedToken.objects.filter(token__jti=token['jti']).exists())
        self.assertEqual(self.refrescar(str(token)).status_code, 200)

    def test_payload_invalido_no_revoca(self):
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
        for datos in ({}, {'refresh': ''}, {'refresh': '   '}, {'refresh': None},
                      {'refresh': 123}, {'refresh': True}, {'refresh': []}, {'refresh': {}}, []):
            self.assertEqual(self.api.post('/api/auth/logout/', datos, format='json').status_code, 400)
        self.assertFalse(BlacklistedToken.objects.exists())

    def test_refresh_invalido_expirado_tipo_incorrecto_y_firma_alterada(self):
        from datetime import timedelta
        from rest_framework_simplejwt.tokens import RefreshToken
        expirado = RefreshToken.for_user(self.usuario)
        expirado.set_exp(lifetime=timedelta(seconds=-1))
        partes = self.par['refresh'].split('.')
        partes[2] = ('A' if partes[2][0] != 'A' else 'B') + partes[2][1:]
        for token in ('no-es-un-token', str(expirado), self.par['access'], '.'.join(partes)):
            respuesta = self.cerrar(token)
            self.assertEqual(respuesta.status_code, 400)
            self.assertEqual(str(respuesta.data['refresh'][0]), 'Refresh token inválido.')

    def test_access_ausente_invalido_expirado_y_sesion_html_no_bastan(self):
        from datetime import timedelta
        from rest_framework_simplejwt.tokens import AccessToken
        expirado = AccessToken.for_user(self.usuario)
        expirado.set_exp(lifetime=timedelta(seconds=-1))
        self.api.force_login(self.usuario)
        for token in (None, 'invalido', str(expirado)):
            self.api.credentials(**({'HTTP_AUTHORIZATION': 'Bearer ' + token} if token else {}))
            self.assertEqual(self.cerrar(self.par['refresh']).status_code, 401)
        self.api.credentials(HTTP_AUTHORIZATION='Bearer ' + self.par['access'])
        self.assertEqual(self.refrescar(self.par['refresh']).status_code, 200)

    def test_get_autenticado_no_revoca(self):
        self.assertEqual(self.api.get('/api/auth/logout/').status_code, 405)
        self.assertEqual(self.refrescar(self.par['refresh']).status_code, 200)

    def test_logout_solo_afecta_refresh_presentado_y_preserva_sesion_html(self):
        otro_par = self.obtener_par(self.usuario.email)
        self.client.force_login(self.usuario)
        self.assertEqual(self.cerrar(self.par['refresh']).status_code, 204)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.usuario.pk)
        self.assertEqual(self.refrescar(otro_par['refresh']).status_code, 200)
        self.assertRedirects(self.client.get('/logout/'), '/', fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_refresh_usuario_eliminado_responde_401_generico(self):
        from core.serializers import RefreshJWTSerializer
        self.usuario.delete()
        respuesta = self.refrescar(self.par['refresh'])
        self.assertEqual(respuesta.status_code, 401)
        self.assertEqual(set(respuesta.data), {'detail'})
        self.assertEqual(str(respuesta.data['detail']), str(RefreshJWTSerializer.default_error_messages['no_active_account']))
        self.assertEqual(respuesta.data['detail'].code, 'no_active_account')
        self.assertNotIn('access', respuesta.data)
        self.assertNotIn('refresh', respuesta.data)

    def test_refresh_usuario_inactivo_no_emite_ni_rota(self):
        from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
        from core.serializers import RefreshJWTSerializer
        self.usuario.is_active = False
        self.usuario.save(update_fields=['is_active'])
        cantidad = OutstandingToken.objects.count()
        respuesta = self.refrescar(self.par['refresh'])
        self.assertEqual(respuesta.status_code, 401)
        self.assertEqual(set(respuesta.data), {'detail'})
        self.assertEqual(str(respuesta.data['detail']), str(RefreshJWTSerializer.default_error_messages['no_active_account']))
        self.assertEqual(OutstandingToken.objects.count(), cantidad)
        self.assertFalse(BlacklistedToken.objects.exists())

    def test_refresh_expirado_sigue_rechazado(self):
        from datetime import timedelta
        from rest_framework_simplejwt.tokens import RefreshToken
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
        token = RefreshToken.for_user(self.usuario)
        token.set_exp(lifetime=timedelta(seconds=-1))
        respuesta = self.refrescar(str(token))
        self.assertEqual(respuesta.status_code, 401)
        self.assertNotIn('access', respuesta.data)
        self.assertNotIn('refresh', respuesta.data)
        self.assertFalse(BlacklistedToken.objects.exists())


def resultado_ia_simulado(estado='EXITO'):
    seleccionadas, procesadas, omitidas, fallidas = {
        'EXITO': (1, 1, 0, 0), 'PARCIAL': (2, 1, 0, 1), 'FALLO': (1, 0, 0, 1),
        'NO_DISPONIBLE': (1, 0, 0, 1), 'SIN_PENDIENTES': (0, 0, 0, 0),
    }[estado]
    return {
        'estado': estado, 'seleccionadas': seleccionadas, 'procesadas': procesadas,
        'omitidas': omitidas, 'fallidas': fallidas,
        'errores': [{'id_publicacion_api': 1, 'codigo': (
            'servicio_no_disponible' if estado == 'NO_DISPONIBLE' else 'llamada_gemini'
        )}] if fallidas else [],
        'mensaje': 'Resumen IA de prueba.',
    }


class GeminiIntegridadTestCase(TestCase):
    def setUp(self):
        from unittest.mock import Mock
        from core.services.gemini_cliente import GeminiCliente
        with patch('core.services.gemini_cliente.genai'):
            self.cliente = GeminiCliente(api_key='clave-ficticia-test')
        self.cliente.client = Mock()
        self.cliente.types = Mock()
        self.pub = Publicacion.objects.create(hash_origen='gemini-test', contenido='Original')
        self.data = {
            'polaridad': 0.5, 'confianza': 0.8,
            'localidades': [{'nombre': 'Posadas', 'latitud': -27.3, 'longitud': -55.9}],
        }
        self.generar = self.cliente.client.models.generate_content
        self.generar.return_value.text = json.dumps(self.data)
        espera = patch('core.services.gemini_cliente.time.sleep')
        self.espera = espera.start()
        self.addCleanup(espera.stop)
        salida = patch('builtins.print')
        self.salida = salida.start()
        self.addCleanup(salida.stop)

    def procesar(self):
        return self.cliente.procesar_publicaciones_con_ia()

    def assert_sin_resultados(self):
        from core.models import Locacion
        self.pub.refresh_from_db()
        self.assertFalse(self.pub.procesado_ia)
        self.assertFalse(Sentimiento.objects.exists())
        self.assertFalse(Locacion.objects.exists())

    def test_respuesta_valida_y_reintento_no_duplica(self):
        from core.models import Locacion
        self.assertEqual(self.procesar()['procesadas'], 1)
        self.pub.refresh_from_db()
        self.assertTrue(self.pub.procesado_ia)
        sentimiento = Sentimiento.objects.get()
        self.assertEqual((sentimiento.polaridad, sentimiento.confianza), (0.5, 0.8))
        locacion = Locacion.objects.get()
        self.assertEqual((locacion.location, locacion.latitud, locacion.longitud),
                         ('Posadas', -27.3, -55.9))
        self.procesar()
        self.generar.assert_called_once()
        self.assertEqual(Sentimiento.objects.count(), 1)
        self.assertEqual(Locacion.objects.count(), 1)

    def test_respuestas_invalidas_no_escriben(self):
        respuestas = ['', 'no-json', 'null', '[]', '{}',
                      '{"polaridad":0,"confianza":0,"confianza":1,"localidades":[]}']
        for campo, valores in (
            ('confianza', [None, True, False, '0.8', -0.1, 1.1, float('nan'), float('inf'), {}, []]),
            ('polaridad', [None, True, '0', -1.1, 1.1, float('-inf')]),
            ('localidades', [None, {}, [None], [{}], [dict(self.data['localidades'][0], nombre='')],
                             [dict(self.data['localidades'][0], nombre='x' * 19)],
                             [dict(self.data['localidades'][0], latitud=91)],
                             [dict(self.data['localidades'][0], longitud='0')],
                             self.data['localidades'] * 2]),
        ):
            for valor in valores:
                respuestas.append(json.dumps(dict(self.data, **{campo: valor})))
            incompleta = dict(self.data)
            del incompleta[campo]
            respuestas.append(json.dumps(incompleta))
        for respuesta in respuestas:
            with self.subTest(respuesta=respuesta):
                self.generar.return_value.text = respuesta
                self.procesar()
                self.assert_sin_resultados()
        self.espera.assert_not_called()

    def test_localidades_invalidas_y_propiedades_adicionales(self):
        from core.services.gemini_cliente import validar_respuesta_gemini
        localidades = []
        for nombre in (None, True, 1, [], {}, '', '   ', 'x' * 19):
            localidades.append(dict(self.data['localidades'][0], nombre=nombre))
        for campo in ('latitud', 'longitud'):
            for valor in (None, True, '0', float('nan'), float('inf'), float('-inf'), -181, 181):
                localidades.append(dict(self.data['localidades'][0], **{campo: valor}))
            incompleta = dict(self.data['localidades'][0])
            del incompleta[campo]
            localidades.append(incompleta)
        localidades.append(dict(self.data['localidades'][0], extra=0))
        respuestas = [json.dumps(dict(self.data, localidades=[loc])) for loc in localidades]
        respuestas.extend([
            json.dumps(dict(self.data, extra=0)),
            '{"polaridad":0,"confianza":1,"localidades":'
            '[{"nombre":"Posadas","latitud":0,"latitud":1,"longitud":0}]}',
            json.dumps(dict(self.data, localidades=[
                self.data['localidades'][0], dict(self.data['localidades'][0], latitud=0),
            ])),
        ])
        for respuesta in respuestas:
            with self.subTest(respuesta=respuesta):
                with self.assertRaises(ValueError):
                    validar_respuesta_gemini(respuesta)

    def test_coordenadas_limite_y_nombre_maximo_validos(self):
        from core.services.gemini_cliente import validar_respuesta_gemini
        for latitud in (-90, 0, 90):
            for longitud in (-180, 0, 180):
                loc = {'nombre': 'x' * 18, 'latitud': latitud, 'longitud': longitud}
                resultado = validar_respuesta_gemini(json.dumps(dict(self.data, localidades=[loc])))
                self.assertEqual(resultado['localidades'], [loc])

    def test_edicion_durante_gemini_no_se_sobrescribe(self):
        def generar(**kwargs):
            Publicacion.objects.filter(pk=self.pub.pk).update(contenido='Texto editado')
            return self.generar.return_value
        self.generar.side_effect = generar
        self.assertEqual(self.procesar()['procesadas'], 1)
        self.pub.refresh_from_db()
        self.assertEqual(self.pub.contenido, 'Texto editado')
        self.assertTrue(self.pub.procesado_ia)
        self.assertEqual(Sentimiento.objects.get().polaridad, 0.5)

    def test_fallo_espera_no_se_informa_como_error_de_analisis(self):
        self.espera.side_effect = RuntimeError('fallo de espera')
        resultado = self.procesar()
        self.assertEqual(resultado['estado'], 'EXITO')
        self.assertEqual((resultado['seleccionadas'], resultado['procesadas'],
                          resultado['omitidas'], resultado['fallidas']), (1, 1, 0, 0))
        self.assertEqual(resultado['errores'], [])
        self.salida.assert_not_called()
        self.pub.refresh_from_db()
        self.assertTrue(self.pub.procesado_ia)
        self.assertEqual(Sentimiento.objects.get().confianza, 0.8)

    def test_fallo_espera_continua_lote_sin_reintentar_commits(self):
        from core.models import Locacion
        otra = Publicacion.objects.create(hash_origen='espera-otra', contenido='Otra')
        self.espera.side_effect = RuntimeError('fallo de espera')
        resultado = self.procesar()
        self.assertEqual(resultado['estado'], 'EXITO')
        self.assertEqual((resultado['seleccionadas'], resultado['procesadas'],
                          resultado['omitidas'], resultado['fallidas']), (2, 2, 0, 0))
        self.assertEqual(resultado['errores'], [])
        self.assertEqual(self.generar.call_count, 2)
        self.assertEqual(self.espera.call_count, 2)
        for pub in (self.pub, otra):
            pub.refresh_from_db()
            self.assertTrue(pub.procesado_ia)
            self.assertEqual(Sentimiento.objects.filter(id_publicacion_api=pub).count(), 1)
            self.assertEqual(Locacion.objects.filter(id_publicacion_api=pub).count(), 1)
        reintento = self.procesar()
        self.assertEqual(reintento['estado'], 'SIN_PENDIENTES')
        self.assertEqual(reintento['seleccionadas'], 0)
        self.assertEqual(self.generar.call_count, 2)

    def test_interrupciones_de_espera_no_se_ocultan(self):
        for interrupcion in (KeyboardInterrupt, SystemExit):
            with self.subTest(interrupcion=interrupcion):
                self.pub.procesado_ia = False
                self.pub.save(update_fields=['procesado_ia'])
                Sentimiento.objects.all().delete()
                from core.models import Locacion
                Locacion.objects.all().delete()
                self.espera.side_effect = interrupcion()
                with self.assertRaises(interrupcion):
                    self.procesar()
                self.pub.refresh_from_db()
                self.assertTrue(self.pub.procesado_ia)

    def test_limites_y_lista_vacia_validos(self):
        from core.services.gemini_cliente import validar_respuesta_gemini
        for polaridad in (-1, 0, 1):
            for confianza in (0, 1):
                resultado = validar_respuesta_gemini(json.dumps({
                    'polaridad': polaridad, 'confianza': confianza, 'localidades': [],
                }))
                self.assertEqual(resultado['confianza'], confianza)

    def test_localidad_final_invalida_no_produce_escrituras(self):
        self.data['localidades'].append({'nombre': 'Oberá', 'latitud': None, 'longitud': 0})
        self.generar.return_value.text = json.dumps(self.data)
        with patch('core.services.gemini_cliente.Sentimiento.objects.create') as sentimiento, \
                patch('core.services.gemini_cliente.Locacion.objects.create') as locacion:
            self.procesar()
        sentimiento.assert_not_called()
        locacion.assert_not_called()
        self.assert_sin_resultados()

    def test_fallo_externo_aislado_no_impide_siguiente_publicacion(self):
        from unittest.mock import Mock
        otra = Publicacion.objects.create(hash_origen='gemini-otra', contenido='Otro texto')

        def generar(**kwargs):
            if kwargs['contents'].endswith('Original'):
                raise RuntimeError('Gemini simulado no disponible')
            return Mock(text=json.dumps(self.data))

        self.generar.side_effect = generar
        self.assertEqual(self.procesar()['procesadas'], 1)
        self.pub.refresh_from_db()
        otra.refresh_from_db()
        self.assertFalse(self.pub.procesado_ia)
        self.assertTrue(otra.procesado_ia)
        self.assertEqual(Sentimiento.objects.get().id_publicacion_api_id, otra.pk)

    def test_fallos_persistencia_hacen_rollback_y_permiten_reintento(self):
        self.data['localidades'].append({'nombre': 'Oberá', 'latitud': -27, 'longitud': -55})
        self.generar.return_value.text = json.dumps(self.data)
        from core.models import Locacion
        crear_locacion = Locacion.objects.create
        for punto in ('sentimiento', 'segunda_locacion', 'estado'):
            with self.subTest(punto=punto):
                llamadas = 0

                def crear(**datos):
                    nonlocal llamadas
                    llamadas += 1
                    if llamadas == 2:
                        raise IntegrityError('fallo simulado')
                    return crear_locacion(**datos)

                if punto == 'sentimiento':
                    parche = patch('core.services.gemini_cliente.Sentimiento.objects.create',
                                   side_effect=IntegrityError('fallo simulado'))
                elif punto == 'segunda_locacion':
                    parche = patch('core.services.gemini_cliente.Locacion.objects.create', side_effect=crear)
                else:
                    parche = patch('core.services.gemini_cliente.Publicacion.save',
                                   side_effect=IntegrityError('fallo simulado'))
                with parche:
                    self.procesar()
                self.assert_sin_resultados()
        self.procesar()
        self.assertEqual(Sentimiento.objects.count(), 1)
        self.assertEqual(Locacion.objects.count(), 2)

    def test_actualiza_sentimiento_unico_y_rollback_preserva_anterior(self):
        anterior = Sentimiento.objects.create(id_publicacion_api=self.pub, polaridad=-0.5, confianza=0.2)
        with patch('core.services.gemini_cliente.Locacion.objects.create', side_effect=IntegrityError('fallo')):
            self.procesar()
        anterior.refresh_from_db()
        self.assertEqual(anterior.confianza, 0.2)
        self.procesar()
        anterior.refresh_from_db()
        self.assertEqual(anterior.confianza, 0.8)
        self.assertEqual(Sentimiento.objects.count(), 1)

    def test_conflictos_preservan_datos_historicos(self):
        from core.models import Locacion
        primero = Sentimiento.objects.create(id_publicacion_api=self.pub, polaridad=-0.5, confianza=0.2)
        segundo = Sentimiento.objects.create(id_publicacion_api=self.pub, polaridad=0.1, confianza=0.3)
        resultado = self.procesar()
        self.assertEqual(resultado['errores'][0]['codigo'], 'sentimientos_multiples')
        self.assertEqual(list(Sentimiento.objects.order_by('pk').values_list('confianza', flat=True)), [0.2, 0.3])
        segundo.delete()  # Sólo fixture de la base aislada de tests.
        loc = Locacion.objects.create(id_publicacion_api=self.pub, location='Histórica', latitud=0, longitud=0)
        resultado = self.procesar()
        self.assertEqual(resultado['errores'][0]['codigo'], 'locaciones_preexistentes')
        primero.refresh_from_db()
        self.assertEqual(primero.confianza, 0.2)
        self.assertEqual(Locacion.objects.get().pk, loc.pk)
        self.pub.refresh_from_db()
        self.assertFalse(self.pub.procesado_ia)

    def test_revalida_estado_actual_y_no_sobrescribe_contenido(self):
        def respuesta(**kwargs):
            Publicacion.objects.filter(pk=self.pub.pk).update(contenido='Editado', procesado_ia=True)
            return self.generar.return_value
        self.generar.side_effect = respuesta
        self.procesar()
        self.pub.refresh_from_db()
        self.assertEqual(self.pub.contenido, 'Editado')
        self.assertFalse(Sentimiento.objects.exists())
        self.espera.assert_not_called()
        self.pub.procesado_ia = False
        self.pub.save(update_fields=['procesado_ia'])
        self.generar.side_effect = None
        guardar_original = Publicacion.save
        with patch('core.services.gemini_cliente.Publicacion.save', autospec=True,
                   side_effect=guardar_original) as guardar:
            self.procesar()
            self.assertEqual(guardar.call_args.kwargs, {'update_fields': ['procesado_ia']})
        self.pub.refresh_from_db()
        self.assertTrue(self.pub.procesado_ia)


class GeminiTransaccionesTestCase(TransactionTestCase):
    def test_concurrencia_y_llamadas_fuera_de_atomic(self):
        from concurrent.futures import ThreadPoolExecutor
        from queue import Queue
        from threading import Event
        from time import monotonic
        from unittest.mock import Mock
        from django.db import connection
        from core.models import Locacion
        from core.services.gemini_cliente import GeminiCliente
        if connection.vendor != 'postgresql':
            self.skipTest('La garantía de bloqueo requiere PostgreSQL.')
        pub = Publicacion.objects.create(hash_origen='gemini-concurrente', contenido='Texto')
        primera_bloqueada = Event()
        liberar_primera = Event()
        segundo_intenta_bloquear = Event()
        pids = Queue()
        llamadas = Queue()
        bloqueos = Queue()

        def generar(**kwargs):
            llamadas.put(('gemini', connections['default'].in_atomic_block, kwargs['contents']))
            return Mock(text=json.dumps({
                'polaridad': 0, 'confianza': 1,
                'localidades': [{'nombre': 'Posadas', 'latitud': 0, 'longitud': 0}],
            }))

        def esperar(segundos):
            llamadas.put(('espera', connections['default'].in_atomic_block, segundos))

        def procesar(primero):
            conexion = connections['default']
            try:
                with conexion.cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid()')
                    pids.put((primero, cursor.fetchone()[0]))
                    cursor.execute("SET lock_timeout = '15s'")

                def observar_bloqueo(execute, sql, params, many, context):
                    if 'FOR UPDATE' not in sql:
                        return execute(sql, params, many, context)
                    bloqueos.put((primero, sql, params, conexion.in_atomic_block))
                    if not primero:
                        segundo_intenta_bloquear.set()
                    resultado = execute(sql, params, many, context)
                    if primero:
                        # execute ya adquirió el bloqueo real; mantenerlo hasta que
                        # el hilo principal observe al segundo esperando en PostgreSQL.
                        primera_bloqueada.set()
                        if not liberar_primera.wait(timeout=15):
                            raise RuntimeError('Timeout esperando liberación del primer bloqueo')
                    return resultado

                cliente = GeminiCliente(api_key='clave-ficticia-test')
                cliente.client = Mock()
                cliente.types = Mock()
                cliente.client.models.generate_content.side_effect = generar
                with conexion.execute_wrapper(observar_bloqueo):
                    return cliente.procesar_publicaciones_con_ia()
            finally:
                conexion.close()

        with patch('core.services.gemini_cliente.genai'), \
                patch('core.services.gemini_cliente.time.sleep', side_effect=esperar), \
                patch('builtins.print') as salida:
            with ThreadPoolExecutor(max_workers=2) as executor:
                primera = executor.submit(procesar, True)
                try:
                    self.assertTrue(primera_bloqueada.wait(timeout=10),
                                    'La primera conexión no adquirió el bloqueo')
                    segunda = executor.submit(procesar, False)
                    self.assertTrue(segundo_intenta_bloquear.wait(timeout=10),
                                    'La segunda conexión no intentó adquirir el bloqueo')
                    identificadores = dict(pids.get(timeout=5) for _ in range(2))
                    self.assertNotEqual(identificadores[True], identificadores[False])
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT pg_backend_pid()')
                        observador = cursor.fetchone()[0]
                    self.assertNotIn(observador, identificadores.values())

                    limite = monotonic() + 10
                    bloqueo_observado = False
                    while monotonic() < limite:
                        with connection.cursor() as cursor:
                            cursor.execute(
                                "SELECT pg_blocking_pids(%s), wait_event_type "
                                "FROM pg_stat_activity WHERE pid = %s",
                                [identificadores[False], identificadores[False]],
                            )
                            estado = cursor.fetchone()
                        if estado and identificadores[True] in estado[0] and estado[1] == 'Lock':
                            bloqueo_observado = True
                            break
                        # Sondeo acotado de un estado del servidor, sin liberar por tiempo.
                        liberar_primera.wait(timeout=0.01)
                    self.assertTrue(bloqueo_observado,
                                    'PostgreSQL no mostró al segundo bloqueado por el primero')
                    self.assertFalse(primera.done())
                    self.assertFalse(segunda.done())
                finally:
                    liberar_primera.set()
                resultados = [primera.result(timeout=20), segunda.result(timeout=20)]
            salida.assert_not_called()

        self.assertEqual(resultados[0]['procesadas'], 1)
        self.assertEqual(resultados[1]['omitidas'], 1)
        for resultado in resultados:
            self.assertEqual(resultado['estado'], 'EXITO')
            self.assertEqual(resultado['fallidas'], 0)
            self.assertEqual(resultado['errores'], [])
            self.assertEqual(resultado['seleccionadas'], resultado['procesadas']
                             + resultado['omitidas'] + resultado['fallidas'])
        observaciones = [bloqueos.get_nowait() for _ in range(bloqueos.qsize())]
        self.assertEqual(len(observaciones), 2)
        for _, sql, params, en_atomic in observaciones:
            self.assertIn('"Publicacion"', sql)
            self.assertEqual(tuple(params), (pub.pk,))
            self.assertTrue(en_atomic)
        estados = [llamadas.get_nowait() for _ in range(llamadas.qsize())]
        self.assertEqual(sum(tipo == 'gemini' for tipo, _, _ in estados), 2)
        self.assertEqual(sum(tipo == 'espera' for tipo, _, _ in estados), 1)
        for tipo, en_atomic, argumento in estados:
            self.assertFalse(en_atomic, tipo)
            if tipo == 'espera':
                self.assertEqual(argumento, 12)
        sentimiento = Sentimiento.objects.get()
        self.assertEqual((sentimiento.id_publicacion_api_id, sentimiento.polaridad, sentimiento.confianza),
                         (pub.pk, 0, 1))
        locacion = Locacion.objects.get()
        self.assertEqual((locacion.id_publicacion_api_id, locacion.location,
                          locacion.latitud, locacion.longitud), (pub.pk, 'Posadas', 0, 0))
        pub.refresh_from_db()
        self.assertTrue(pub.procesado_ia)


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

    @patch('core.views.procesar_publicaciones_con_ia', return_value=resultado_ia_simulado())
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
            ('procesar_publicaciones_con_ia', resultado_ia_simulado()),
            ('analyze_sentiment_lexicon', 0.5),
            ('compute_probabilistic_sentiment', {'confidence_score': 80.0}),
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
            return_value=resultado_ia_simulado(),
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
            return resultado_ia_simulado()

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
            ('compute_probabilistic_sentiment', {'confidence_score': 80.0}),
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
                patch('core.views.compute_probabilistic_sentiment', return_value={'confidence_score': 80.0}) as probabilistico, \
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


class EscritoresLocalesIntegridadTestCase(TestCase):
    def setUp(self):
        from rest_framework.test import APIClient
        self.usuario = get_user_model().objects.create_superuser(username='integridad-local')
        self.api = APIClient()
        self.api.force_authenticate(self.usuario)
        self.pub = Publicacion.objects.create(hash_origen='integridad-local', contenido='bueno')

    def reprocesar(self):
        return self.api.post(f'/api/publicaciones/{self.pub.pk}/procesar-sentimiento/')

    def crear(self):
        return self.api.post('/api/publicaciones/crear/', {
            'titulo': 'Alta integridad', 'contenido': 'bueno',
        }, format='json')

    def test_confianza_real_normalizada_y_batch_preserva_porcentaje(self):
        self.assertEqual(self.crear().data['sentimiento']['confianza'], 0.4)
        respuesta = self.reprocesar()
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.data['sentimiento']['confianza'], 0.4)
        self.assertEqual(Sentimiento.objects.get(id_publicacion_api=self.pub).confianza, 0.4)
        batch = self.api.post('/api/sentiment/batch-analyze/', {
            'comments': [{'message': 'bueno'}],
        }, format='json')
        self.assertEqual(batch.data['confidence_score'], 40.0)

    def test_porcentajes_limite(self):
        for porcentaje in (0, 100):
            with self.subTest(porcentaje=porcentaje), patch(
                    'core.views.compute_probabilistic_sentiment',
                    return_value={'confidence_score': porcentaje}):
                respuesta = self.reprocesar()
                self.assertEqual(respuesta.data['sentimiento']['confianza'], porcentaje / 100)
        self.assertEqual(Sentimiento.objects.filter(id_publicacion_api=self.pub).count(), 1)

    def test_confianza_invalida_revierte_alta_y_reprocesamiento(self):
        anterior = Sentimiento.objects.create(id_publicacion_api=self.pub, polaridad=-0.5, confianza=0.2)
        for analisis in ({}, None, {'confidence_score': None}, {'confidence_score': True},
                         {'confidence_score': '80'}, {'confidence_score': -1},
                         {'confidence_score': 101}, {'confidence_score': float('nan')},
                         {'confidence_score': float('inf')}):
            with self.subTest(analisis=analisis), patch(
                    'core.views.compute_probabilistic_sentiment', return_value=analisis):
                for operacion in (self.crear, self.reprocesar):
                    with self.assertRaises(ValueError):
                        operacion()
                self.assertEqual(Publicacion.objects.count(), 1)
                anterior.refresh_from_db()
                self.assertEqual((anterior.polaridad, anterior.confianza), (-0.5, 0.2))
                self.pub.refresh_from_db()
                self.assertFalse(self.pub.procesado_ia)

    def test_fallos_sentimiento_y_estado_revierten_alta(self):
        for punto in ('Sentimiento.objects.create', 'Publicacion.save'):
            with self.subTest(punto=punto), patch('core.views.' + punto,
                                                  side_effect=IntegrityError('fallo simulado')):
                with self.assertRaises(IntegrityError):
                    self.crear()
            self.assertEqual(Publicacion.objects.count(), 1)
            self.assertFalse(Sentimiento.objects.exists())

    def test_fallo_estado_revierte_actualizacion_de_sentimiento(self):
        anterior = Sentimiento.objects.create(id_publicacion_api=self.pub, polaridad=-0.5, confianza=0.2)
        with patch('core.views.Publicacion.save', side_effect=IntegrityError('fallo simulado')):
            with self.assertRaises(IntegrityError):
                self.reprocesar()
        anterior.refresh_from_db()
        self.assertEqual((anterior.polaridad, anterior.confianza), (-0.5, 0.2))
        self.pub.refresh_from_db()
        self.assertFalse(self.pub.procesado_ia)

    def test_sentimientos_multiples_generan_409_sin_cambios(self):
        from core.models import Locacion
        for confianza in (0.2, 0.3):
            Sentimiento.objects.create(id_publicacion_api=self.pub, polaridad=-0.5, confianza=confianza)
        Locacion.objects.create(id_publicacion_api=self.pub, location='Histórica', latitud=0, longitud=0)
        antes = list(Sentimiento.objects.order_by('pk').values())
        with patch('core.views.analyze_sentiment_lexicon') as lexicon, \
                patch('core.views.compute_probabilistic_sentiment') as probabilistico:
            respuesta = self.reprocesar()
        lexicon.assert_not_called()
        probabilistico.assert_not_called()
        self.assertEqual(respuesta.status_code, 409)
        self.assertEqual(respuesta.data['codigo'], 'sentimientos_multiples')
        self.assertEqual(list(Sentimiento.objects.order_by('pk').values()), antes)
        self.assertEqual(Locacion.objects.count(), 1)
        self.pub.refresh_from_db()
        self.assertFalse(self.pub.procesado_ia)


    def test_excepcion_analizador_revierte_alta_y_preserva_reprocesamiento(self):
        anterior = Sentimiento.objects.create(id_publicacion_api=self.pub, polaridad=-0.5, confianza=0.2)
        with patch('core.views.analyze_sentiment_lexicon', side_effect=RuntimeError('fallo léxico')):
            for operacion in (self.crear, self.reprocesar):
                with self.assertRaisesMessage(RuntimeError, 'fallo léxico'):
                    operacion()
        self.assertEqual(Publicacion.objects.count(), 1)
        anterior.refresh_from_db()
        self.assertEqual((anterior.polaridad, anterior.confianza), (-0.5, 0.2))
        self.pub.refresh_from_db()
        self.assertFalse(self.pub.procesado_ia)

    def test_fallo_durante_actualizacion_revierte_sentimiento(self):
        anterior = Sentimiento.objects.create(id_publicacion_api=self.pub, polaridad=-0.5, confianza=0.2)
        guardar = Sentimiento.save

        def guardar_y_fallar(instancia, **kwargs):
            guardar(instancia, **kwargs)
            raise IntegrityError('fallo actualización')

        with patch.object(Sentimiento, 'save', guardar_y_fallar):
            with self.assertRaises(IntegrityError):
                self.reprocesar()
        anterior.refresh_from_db()
        self.assertEqual((anterior.polaridad, anterior.confianza), (-0.5, 0.2))
        self.pub.refresh_from_db()
        self.assertFalse(self.pub.procesado_ia)


class SentimientoAdminIntegridadTestCase(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_superuser(username='integridad-admin')
        self.client.force_login(self.usuario)
        self.pub = Publicacion.objects.create(hash_origen='admin-integridad', contenido='Texto')
        self.ruta = '/admin/core/sentimiento/add/'
        self.datos = {'id_publicacion_api': self.pub.pk, 'polaridad': 0.5, 'confianza': 0.8, '_save': 'Guardar'}

    def test_admin_valida_confianza_y_crea_unico(self):
        for confianza in (-1, 1.1, 'NaN', 'Infinity', '', None):
            with self.subTest(confianza=confianza):
                datos = dict(self.datos, confianza='' if confianza is None else confianza)
                respuesta = self.client.post(self.ruta, datos)
                self.assertEqual(respuesta.status_code, 200)
                self.assertIn('confianza', respuesta.context['adminform'].form.errors)
                self.assertFalse(Sentimiento.objects.exists())
        self.assertEqual(self.client.post(self.ruta, self.datos).status_code, 302)
        self.assertEqual(Sentimiento.objects.get().confianza, 0.8)
        duplicado = self.client.post(self.ruta, self.datos)
        self.assertEqual(duplicado.status_code, 200)
        self.assertIn('ya tiene un sentimiento', str(duplicado.context['adminform'].form.errors))
        self.assertEqual(Sentimiento.objects.count(), 1)

    def test_admin_conflicto_historico_no_edita_y_no_mueve_publicacion(self):
        primero = Sentimiento.objects.create(id_publicacion_api=self.pub, polaridad=0.1, confianza=0.2)
        Sentimiento.objects.create(id_publicacion_api=self.pub, polaridad=0.1, confianza=0.3)
        ruta = f'/admin/core/sentimiento/{primero.pk}/change/'
        respuesta = self.client.post(ruta, self.datos)
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('sentimientos_multiples', str(respuesta.context['adminform'].form.errors))
        primero.refresh_from_db()
        self.assertEqual(primero.confianza, 0.2)
        self.assertIn('id_publicacion_api', respuesta.context['adminform'].readonly_fields)

    def test_guardado_admin_revalida_duplicados_y_confianza(self):
        from django.contrib import admin
        from core.services.integridad_sentimiento import ConflictoSentimiento
        administrador = admin.site._registry[Sentimiento]
        for valor in (True, None, '0.8', float('nan'), float('inf'), -1, 2):
            with self.subTest(valor=valor):
                obj = Sentimiento(id_publicacion_api=self.pub, polaridad=0, confianza=valor)
                with self.assertRaises(ValueError):
                    administrador.save_model(None, obj, None, False)
        Sentimiento.objects.create(id_publicacion_api=self.pub, polaridad=0, confianza=0.2)
        with self.assertRaises(ConflictoSentimiento):
            administrador.save_model(None, Sentimiento(**{
                'id_publicacion_api': self.pub, 'polaridad': 0, 'confianza': 0.8,
            }), None, False)
        self.assertEqual(Sentimiento.objects.get().confianza, 0.2)

    def test_edicion_admin_valida_limites_y_preserva_publicacion(self):
        from core.admin import SentimientoAdminForm
        obj = Sentimiento.objects.create(id_publicacion_api=self.pub, polaridad=0, confianza=0.2)
        otra = Publicacion.objects.create(hash_origen='otra-admin', contenido='Otro texto')
        for confianza in (0, 1):
            respuesta = self.client.post(f'/admin/core/sentimiento/{obj.pk}/change/',
                                         dict(self.datos, confianza=confianza, id_publicacion_api=otra.pk))
            self.assertEqual(respuesta.status_code, 302)
            obj.refresh_from_db()
            self.assertEqual(obj.confianza, confianza)
            self.assertEqual(obj.id_publicacion_api_id, self.pub.pk)
        form = SentimientoAdminForm(data=dict(self.datos, confianza=True), instance=obj)
        self.assertFalse(form.is_valid())
        self.assertIn('confianza', form.errors)

    def test_admin_revierte_fallo_despues_de_guardar(self):
        from django.contrib import admin
        obj = Sentimiento.objects.create(id_publicacion_api=self.pub, polaridad=0, confianza=0.2)

        def guardar_y_fallar(administrador, request, instancia, form, change):
            instancia.save()
            raise IntegrityError('fallo posterior al guardado')

        with patch.object(admin.ModelAdmin, 'save_model', guardar_y_fallar):
            with self.assertRaises(IntegrityError):
                self.client.post(f'/admin/core/sentimiento/{obj.pk}/change/', self.datos)
        obj.refresh_from_db()
        self.assertEqual((obj.polaridad, obj.confianza), (0, 0.2))

    def test_admin_rechaza_borrado_individual_y_masivo(self):
        from django.contrib import admin
        from django.test import RequestFactory
        obj = Sentimiento.objects.create(id_publicacion_api=self.pub, polaridad=0, confianza=0.2)
        request = RequestFactory().get('/admin/core/sentimiento/')
        request.user = self.usuario
        administrador = admin.site._registry[Sentimiento]
        self.assertFalse(administrador.has_delete_permission(request, obj))
        self.assertNotIn('delete_selected', administrador.get_actions(request))
        self.assertEqual(self.client.post(f'/admin/core/sentimiento/{obj.pk}/delete/',
                                         {'post': 'yes'}).status_code, 403)
        self.assertEqual(self.client.post('/admin/core/sentimiento/', {
            'action': 'delete_selected', '_selected_action': [obj.pk], 'post': 'yes',
        }).status_code, 403)
        self.assertTrue(Sentimiento.objects.filter(pk=obj.pk).exists())

    def test_admin_publicacion_ignora_estado_manipulado_en_alta_y_edicion(self):
        datos = {'titulo': 'Admin', 'contenido': 'Texto', 'fuente': 'Manual',
                 'url': 'https://example.com/admin', 'fecha_captura_0': '2026-10-08',
                 'fecha_captura_1': '12:00:00',
                 'hash_origen': 'hash-manipulado', 'procesado_ia': 'on', '_save': 'Guardar'}
        respuesta = self.client.post('/admin/core/publicacion/add/', datos)
        self.assertEqual(respuesta.status_code, 302)
        nueva = Publicacion.objects.get(titulo='Admin')
        self.assertFalse(nueva.procesado_ia)
        for procesado in (False, True):
            self.pub.procesado_ia = procesado
            self.pub.save(update_fields=['procesado_ia'])
            respuesta = self.client.post(f'/admin/core/publicacion/{self.pub.pk}/change/',
                                         dict(datos, procesado_ia='' if procesado else 'on'))
            self.assertEqual(respuesta.status_code, 302)
            self.pub.refresh_from_db()
            self.assertEqual(self.pub.procesado_ia, procesado)

    def test_admin_rechaza_polaridad_invalida_en_alta_y_edicion(self):
        from core.admin import SentimientoAdminForm
        from django.contrib import admin
        for polaridad in (-1.1, 1.1, 'NaN', 'Infinity', '-Infinity', '', 'True'):
            with self.subTest(polaridad=polaridad):
                respuesta = self.client.post(self.ruta, dict(self.datos, polaridad=polaridad))
                self.assertEqual(respuesta.status_code, 200)
                self.assertIn('polaridad', respuesta.context['adminform'].form.errors)
                self.assertFalse(Sentimiento.objects.exists())
        obj = Sentimiento.objects.create(id_publicacion_api=self.pub, polaridad=0, confianza=0.2)
        for polaridad in (-1.1, 1.1, 'NaN', 'Infinity'):
            respuesta = self.client.post(f'/admin/core/sentimiento/{obj.pk}/change/',
                                         dict(self.datos, polaridad=polaridad))
            self.assertEqual(respuesta.status_code, 200)
            self.assertIn('polaridad', respuesta.context['adminform'].form.errors)
            obj.refresh_from_db()
            self.assertEqual(obj.polaridad, 0)
        form = SentimientoAdminForm(data=dict(self.datos, polaridad=True), instance=obj)
        self.assertFalse(form.is_valid())
        self.assertIn('polaridad', form.errors)
        for valor in (True, None, '0.5', float('nan'), float('inf'), -2, 2):
            obj.polaridad = valor
            with self.assertRaises(ValueError):
                admin.site._registry[Sentimiento].save_model(None, obj, None, True)
        for valor in (-1, 0, 1):
            respuesta = self.client.post(f'/admin/core/sentimiento/{obj.pk}/change/',
                                         dict(self.datos, polaridad=valor))
            self.assertEqual(respuesta.status_code, 302)
            obj.refresh_from_db()
            self.assertEqual(obj.polaridad, valor)


class EscritoresConGeminiConcurrenciaTestCase(TransactionTestCase):
    def test_local_y_admin_coordinan_bloqueo_con_gemini(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from queue import Queue
        from time import monotonic
        from unittest.mock import Mock
        from django.db import connection
        from django.test import Client
        from core.models import Locacion
        from core.services.gemini_cliente import GeminiCliente
        from core.views import ProcesarSentimientoPublicacionView
        if connection.vendor != 'postgresql':
            self.skipTest('El bloqueo requiere PostgreSQL.')
        usuario = get_user_model().objects.create_superuser(username='escritor-concurrente')
        for escritor in ('local', 'admin'):
            with self.subTest(escritor=escritor):
                pub = Publicacion.objects.create(hash_origen='concurrente-' + escritor, contenido='bueno')
                bloqueado, liberar, intentando = Event(), Event(), Event()
                pids = Queue()
                errores = Queue()

                def ejecutar(es_gemini):
                    conexion = connections['default']
                    try:
                        with conexion.cursor() as cursor:
                            cursor.execute('SELECT pg_backend_pid()')
                            pids.put((es_gemini, cursor.fetchone()[0]))
                            cursor.execute("SET lock_timeout = '15s'")

                        def observar(execute, sql, params, many, context):
                            es_bloqueo = 'FOR UPDATE' in sql and '"Publicacion"' in sql
                            if es_bloqueo and es_gemini:
                                intentando.set()
                            resultado = execute(sql, params, many, context)
                            if es_bloqueo and not es_gemini and not bloqueado.is_set():
                                bloqueado.set()
                                if not liberar.wait(timeout=20):
                                    raise RuntimeError('Timeout liberación')
                            return resultado

                        with conexion.execute_wrapper(observar):
                            if es_gemini:
                                cliente = GeminiCliente(api_key='clave-ficticia-test')
                                cliente.client = Mock()
                                cliente.types = Mock()
                                cliente.client.models.generate_content.return_value.text = json.dumps({
                                    'polaridad': 0.5, 'confianza': 0.8, 'localidades': [],
                                })
                                # Limitar el lote al único pendiente de esta subprueba.
                                return cliente.procesar_publicaciones_con_ia(batch_size=1)
                            if escritor == 'local':
                                request = APIRequestFactory().post('/procesar-sentimiento/')
                                force_authenticate(request, user=usuario)
                                return ProcesarSentimientoPublicacionView.as_view()(request, pk=pub.pk).status_code
                            cliente_admin = Client()
                            cliente_admin.force_login(usuario)
                            return cliente_admin.post('/admin/core/sentimiento/add/', {
                                'id_publicacion_api': pub.pk, 'polaridad': 0, 'confianza': 0.4, '_save': 'Guardar',
                            }).status_code
                    except Exception as error:
                        errores.put(error)
                        raise
                    finally:
                        conexion.close()

                with patch('core.services.gemini_cliente.genai'), \
                        patch('core.services.gemini_cliente.time.sleep'), patch('builtins.print') as salida:
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        primero = executor.submit(ejecutar, False)
                        try:
                            self.assertTrue(bloqueado.wait(timeout=10))
                            segundo = executor.submit(ejecutar, True)
                            self.assertTrue(intentando.wait(timeout=10))
                            ids = dict(pids.get(timeout=5) for _ in range(2))
                            self.assertNotEqual(ids[False], ids[True])
                            limite = monotonic() + 10
                            observado = False
                            while monotonic() < limite:
                                with connection.cursor() as cursor:
                                    cursor.execute('SELECT pg_blocking_pids(%s)', [ids[True]])
                                    observado = ids[False] in cursor.fetchone()[0]
                                if observado:
                                    break
                                liberar.wait(timeout=0.01)
                            self.assertTrue(observado, 'Gemini no esperó al escritor local/admin')
                            self.assertFalse(segundo.done())
                        finally:
                            liberar.set()
                        self.assertEqual(primero.result(timeout=20), 200 if escritor == 'local' else 302)
                        resultado = segundo.result(timeout=20)
                    salida.assert_not_called()
                self.assertEqual(resultado['estado'], 'EXITO')
                self.assertEqual(resultado['fallidas'], 0)
                self.assertEqual(resultado['errores'], [])
                self.assertEqual(resultado['seleccionadas'], resultado['procesadas']
                                 + resultado['omitidas'] + resultado['fallidas'])
                self.assertTrue(errores.empty())
                self.assertEqual(resultado['omitidas'] if escritor == 'local' else resultado['procesadas'], 1)
                sentimiento = Sentimiento.objects.get(id_publicacion_api=pub)
                self.assertEqual(sentimiento.confianza, 0.4 if escritor == 'local' else 0.8)
                pub.refresh_from_db()
                self.assertTrue(pub.procesado_ia)
                self.assertFalse(Locacion.objects.filter(id_publicacion_api=pub).exists())


class EscritoresOrdenInversoTestCase(TransactionTestCase):
    def ejecutar_caso(self, primer_tipo, segundo_tipo, sentimiento_inicial=False):
        from concurrent.futures import ThreadPoolExecutor
        from queue import Queue
        from threading import Event, local
        from time import monotonic
        from unittest.mock import Mock
        from django.db import connection
        from django.test import Client
        from core.admin import SentimientoAdminForm
        from core.models import Locacion
        from core.services.gemini_cliente import GeminiCliente
        from core.views import ProcesarSentimientoPublicacionView
        if connection.vendor != 'postgresql':
            self.skipTest('La garantía requiere PostgreSQL.')
        usuario = get_user_model().objects.create_superuser(username=primer_tipo + '-' + segundo_tipo)
        pub = Publicacion.objects.create(hash_origen=usuario.username, contenido='bueno')
        existente = None
        if sentimiento_inicial:
            existente = Sentimiento.objects.create(id_publicacion_api=pub, polaridad=0.1, confianza=0.2)
        bloqueado, liberar, intento = Event(), Event(), Event()
        pids, consultas, validaciones = Queue(), Queue(), Queue()
        contexto = local()
        clean_original = SentimientoAdminForm.clean

        def clean_coordinado(form):
            resultado = clean_original(form)
            if contexto.primero and primer_tipo.startswith('admin'):
                # Pausar DESPUÉS de clean prueba que su bloqueo continúa durante
                # la transición al guardado, gracias a la transacción del Admin.
                validaciones.put(connections['default'].in_atomic_block)
                bloqueado.set()
                if not liberar.wait(timeout=25):
                    raise RuntimeError('Timeout posterior a validación del Admin')
            return resultado

        def ejecutar(tipo, primero):
            contexto.primero = primero
            conexion = connections['default']
            try:
                with conexion.cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid()')
                    pids.put((primero, cursor.fetchone()[0]))
                    cursor.execute("SET lock_timeout = '20s'")

                def observar(execute, sql, params, many, context):
                    bloqueo = 'FOR UPDATE' in sql and '"Publicacion"' in sql
                    if bloqueo:
                        consultas.put((tuple(params), conexion.in_atomic_block))
                        if not primero:
                            intento.set()
                    resultado = execute(sql, params, many, context)
                    if bloqueo and primero and not tipo.startswith('admin') and not bloqueado.is_set():
                        bloqueado.set()
                        if not liberar.wait(timeout=25):
                            raise RuntimeError('Timeout liberación de primer escritor')
                    return resultado

                with conexion.execute_wrapper(observar):
                    if tipo == 'gemini':
                        cliente = GeminiCliente(api_key='clave-ficticia-test')
                        cliente.client = Mock()
                        cliente.types = Mock()
                        cliente.client.models.generate_content.return_value.text = json.dumps({
                            'polaridad': 0.5, 'confianza': 0.8, 'localidades': [],
                        })
                        return {'mensaje': cliente.procesar_publicaciones_con_ia(batch_size=1)}
                    if tipo == 'local':
                        request = APIRequestFactory().post('/procesar-sentimiento/')
                        force_authenticate(request, user=usuario)
                        respuesta = ProcesarSentimientoPublicacionView.as_view()(request, pk=pub.pk)
                        return {'status': respuesta.status_code}
                    cliente_admin = Client()
                    cliente_admin.force_login(usuario)
                    ruta = '/admin/core/sentimiento/add/' if tipo == 'admin_alta' else (
                        f'/admin/core/sentimiento/{existente.pk}/change/')
                    respuesta = cliente_admin.post(ruta, {
                        'id_publicacion_api': pub.pk, 'polaridad': 0.3, 'confianza': 0.6, '_save': 'Guardar',
                    })
                    return {'status': respuesta.status_code, 'contenido': respuesta.content.decode()}
            finally:
                conexion.close()

        with patch('core.services.gemini_cliente.genai'), \
                patch('core.services.gemini_cliente.time.sleep'), \
                patch.object(SentimientoAdminForm, 'clean', clean_coordinado), \
                patch('builtins.print') as salida:
            with ThreadPoolExecutor(max_workers=2) as executor:
                primero = executor.submit(ejecutar, primer_tipo, True)
                try:
                    self.assertTrue(bloqueado.wait(timeout=10), 'El primer escritor no mantuvo el bloqueo')
                    segundo = executor.submit(ejecutar, segundo_tipo, False)
                    self.assertTrue(intento.wait(timeout=10), 'El segundo escritor no intentó bloquear')
                    ids = dict(pids.get(timeout=5) for _ in range(2))
                    self.assertNotEqual(ids[True], ids[False])
                    limite = monotonic() + 10
                    observado = False
                    while monotonic() < limite:
                        with connection.cursor() as cursor:
                            cursor.execute('SELECT pg_blocking_pids(%s)', [ids[False]])
                            observado = ids[True] in cursor.fetchone()[0]
                        if observado:
                            break
                        liberar.wait(timeout=0.01)
                    self.assertTrue(observado, 'PostgreSQL no mostró la espera entre escritores')
                    self.assertFalse(primero.done())
                    self.assertFalse(segundo.done())
                finally:
                    liberar.set()
                resultados = [primero.result(timeout=25), segundo.result(timeout=25)]
            salida.assert_not_called()
        for tipo, resultado in zip((primer_tipo, segundo_tipo), resultados):
            if tipo == 'gemini':
                ia = resultado['mensaje']
                self.assertEqual(ia['procesadas'], 1)
                self.assertEqual(ia['estado'], 'EXITO')
                self.assertEqual(ia['fallidas'], 0)
                self.assertEqual(ia['errores'], [])
                self.assertEqual(ia['seleccionadas'], ia['procesadas']
                                 + ia['omitidas'] + ia['fallidas'])
            elif tipo == 'local':
                self.assertEqual(resultado['status'], 200)
            elif tipo == 'admin_alta' and resultado is resultados[1]:
                self.assertEqual(resultado['status'], 200)
                self.assertIn('ya tiene un sentimiento', resultado['contenido'])
            else:
                self.assertEqual(resultado['status'], 302)
        while not consultas.empty():
            params, en_atomic = consultas.get_nowait()
            self.assertEqual(params, (pub.pk,))
            self.assertTrue(en_atomic)
        if primer_tipo.startswith('admin'):
            self.assertTrue(validaciones.get_nowait())
        sentimiento = Sentimiento.objects.get(id_publicacion_api=pub)
        esperado = {'gemini': (0.5, 0.8), 'local': (0.7, 0.4), 'admin_edicion': (0.3, 0.6),
                    'admin_alta': (0.3, 0.6)}
        vigente = primer_tipo if segundo_tipo == 'admin_alta' else segundo_tipo
        self.assertEqual((sentimiento.polaridad, sentimiento.confianza), esperado[vigente])
        if existente:
            self.assertEqual(sentimiento.pk, existente.pk)
        self.assertFalse(Locacion.objects.filter(id_publicacion_api=pub).exists())
        pub.refresh_from_db()
        self.assertEqual(pub.procesado_ia, 'gemini' in (primer_tipo, segundo_tipo)
                         or 'local' in (primer_tipo, segundo_tipo))

    def test_gemini_primero_frente_a_reprocesamiento(self):
        self.ejecutar_caso('gemini', 'local')

    def test_gemini_primero_frente_a_alta_admin(self):
        self.ejecutar_caso('gemini', 'admin_alta')

    def test_dos_altas_admin_mantienen_bloqueo_entre_clean_y_save(self):
        self.ejecutar_caso('admin_alta', 'admin_alta')

    def test_edicion_admin_y_gemini_en_ambos_ordenes(self):
        for primero, segundo in (('gemini', 'admin_edicion'), ('admin_edicion', 'gemini')):
            with self.subTest(primero=primero):
                self.ejecutar_caso(primero, segundo, sentimiento_inicial=True)


class GeminiResultadosTestCase(TestCase):
    setUp = GeminiIntegridadTestCase.setUp
    procesar = GeminiIntegridadTestCase.procesar

    def assert_invariante(self, resultado):
        self.assertEqual(resultado['seleccionadas'], resultado['procesadas']
                         + resultado['omitidas'] + resultado['fallidas'])
        self.assertEqual(len(resultado['errores']), resultado['fallidas'])
        self.assertIsInstance(resultado['mensaje'], str)

    def test_json_anidado_falla_validacion_y_continua_lote(self):
        from unittest.mock import Mock
        from core.models import Locacion
        otra = Publicacion.objects.create(hash_origen='anidado-otra', contenido='Otra')
        # La primera respuesta fuerza el límite real del decodificador JSON.
        anidado = '{"polaridad":0,"confianza":1,"localidades":' + '[' * 100000 + '0' + ']' * 100000 + '}'
        self.generar.side_effect = [Mock(text=anidado), Mock(text=json.dumps(self.data))]
        # Fijar el orden del lote, manteniendo consulta y persistencia ORM reales.
        pendientes = Publicacion.objects.filter(procesado_ia=False).order_by('pk')
        with patch('core.services.gemini_cliente.Publicacion.objects.filter', return_value=pendientes):
            resultado = self.procesar()
        self.assertEqual(resultado['estado'], 'PARCIAL')
        self.assertEqual((resultado['seleccionadas'], resultado['procesadas'],
                          resultado['omitidas'], resultado['fallidas']), (2, 1, 0, 1))
        self.assert_invariante(resultado)
        self.assertEqual(resultado['errores'], [
            {'id_publicacion_api': self.pub.pk, 'codigo': 'validacion_respuesta'},
        ])
        self.assertNotIn(anidado, json.dumps(resultado))
        self.pub.refresh_from_db()
        self.assertFalse(self.pub.procesado_ia)
        self.assertFalse(Sentimiento.objects.filter(id_publicacion_api=self.pub).exists())
        self.assertFalse(Locacion.objects.filter(id_publicacion_api=self.pub).exists())
        otra.refresh_from_db()
        self.assertTrue(otra.procesado_ia)
        self.assertEqual(Sentimiento.objects.filter(id_publicacion_api=otra).count(), 1)
        self.assertEqual(Locacion.objects.filter(id_publicacion_api=otra).count(), 1)
        self.assertEqual(self.generar.call_count, 2)

    def test_exito_y_fallo_parcial_y_total(self):
        self.generar.return_value.text = '{}'
        fallo = self.procesar()
        self.assertEqual(fallo['estado'], 'FALLO')
        self.assert_invariante(fallo)
        otra = Publicacion.objects.create(hash_origen='resultado-otra', contenido='Otra')
        from unittest.mock import Mock

        def generar(**kwargs):
            return Mock(text='{}' if kwargs['contents'].endswith('Original') else json.dumps(self.data))

        self.generar.side_effect = generar
        parcial = self.procesar()
        self.assertEqual(parcial['estado'], 'PARCIAL')
        self.assertEqual((parcial['procesadas'], parcial['fallidas']), (1, 1))
        self.assert_invariante(parcial)
        self.generar.side_effect = None
        self.generar.return_value.text = json.dumps(self.data)
        exito = self.procesar()
        self.assertEqual(exito['estado'], 'EXITO')
        self.assertEqual(exito['procesadas'], 1)
        self.assert_invariante(exito)
        self.assertTrue(Publicacion.objects.get(pk=otra.pk).procesado_ia)

    def test_indisponibilidad_con_y_sin_pendientes(self):
        self.cliente.client = None
        indisponible = self.procesar()
        self.assertEqual(indisponible['estado'], 'NO_DISPONIBLE')
        self.assertEqual(indisponible['errores'], [
            {'id_publicacion_api': self.pub.pk, 'codigo': 'servicio_no_disponible'},
        ])
        self.assert_invariante(indisponible)
        Publicacion.objects.filter(pk=self.pub.pk).update(procesado_ia=True)
        vacio = self.procesar()
        self.assertEqual(vacio['estado'], 'SIN_PENDIENTES')
        self.assert_invariante(vacio)
        self.generar.assert_not_called()

    def test_error_consulta_no_es_cero_pendientes(self):
        with patch('core.services.gemini_cliente.Publicacion.objects.filter',
                   side_effect=OperationalError('fallo consulta')):
            with self.assertRaises(OperationalError):
                self.procesar()

    def test_omision_y_parcial_con_omision(self):
        from unittest.mock import Mock

        def generar(**kwargs):
            if kwargs['contents'].endswith('Original'):
                Publicacion.objects.filter(pk=self.pub.pk).update(procesado_ia=True)
                return Mock(text=json.dumps(self.data))
            return Mock(text='{}')

        self.generar.side_effect = generar
        omitido = self.procesar()
        self.assertEqual((omitido['estado'], omitido['omitidas']), ('EXITO', 1))
        self.assert_invariante(omitido)
        Publicacion.objects.filter(pk=self.pub.pk).update(procesado_ia=False)
        Publicacion.objects.create(hash_origen='resultado-fallida', contenido='Falla')
        parcial = self.procesar()
        self.assertEqual((parcial['estado'], parcial['omitidas'], parcial['fallidas']), ('PARCIAL', 1, 1))
        self.assert_invariante(parcial)

    def test_codigos_estables_sin_respuestas_ni_excepciones_sensibles(self):
        from unittest.mock import Mock
        from core.models import Locacion
        secreto = 'SECRETO-NO-EXPONER'
        for confianza in (0.2, 0.3):
            Sentimiento.objects.create(id_publicacion_api=self.pub, polaridad=0, confianza=confianza)
        loc = Publicacion.objects.create(hash_origen='resultado-loc', contenido='Loc')
        Locacion.objects.create(id_publicacion_api=loc, location='Histórica', latitud=0, longitud=0)
        persistencia = Publicacion.objects.create(hash_origen='resultado-db', contenido='DB')
        invalida = Publicacion.objects.create(hash_origen='resultado-json', contenido='JSON')
        externa = Publicacion.objects.create(hash_origen='resultado-externa', contenido='Externa')

        def generar(**kwargs):
            contenido = kwargs['contents']
            if contenido.endswith('Externa'):
                raise RuntimeError(secreto)
            return Mock(text=secreto if contenido.endswith('JSON') else json.dumps(self.data))

        self.generar.side_effect = generar
        with patch('core.services.gemini_cliente.Sentimiento.objects.create',
                   side_effect=IntegrityError(secreto)):
            resultado = self.procesar()
        self.assertEqual(resultado['estado'], 'FALLO')
        self.assert_invariante(resultado)
        codigos = {e['id_publicacion_api']: e['codigo'] for e in resultado['errores']}
        self.assertEqual(codigos, {
            self.pub.pk: 'sentimientos_multiples', loc.pk: 'locaciones_preexistentes',
            persistencia.pk: 'persistencia', invalida.pk: 'validacion_respuesta',
            externa.pk: 'llamada_gemini',
        })
        self.assertNotIn(secreto, json.dumps(resultado))
        self.salida.assert_not_called()


class ConsumidoresResultadoIATestCase(TestCase):
    def setUp(self):
        from rest_framework.test import APIClient
        self.usuario = get_user_model().objects.create_superuser(username='resultado-consumidor')
        self.client.force_login(self.usuario)
        self.api = APIClient()
        self.api.force_authenticate(self.usuario)

    def test_cinco_estados_en_vistas_y_endpoint_alternativo(self):
        from django.test import RequestFactory
        from core.services.gemini_cliente import disparar_ingesta as alternativa
        for estado, codigo, status_cuerpo in (
            ('EXITO', 200, 'success'), ('PARCIAL', 200, 'partial'), ('FALLO', 500, 'error'),
            ('NO_DISPONIBLE', 503, 'error'), ('SIN_PENDIENTES', 200, 'success'),
        ):
            with self.subTest(estado=estado):
                resultado = resultado_ia_simulado(estado)
                resumen_ingesta = {'status': 'EXITO', 'capturados': 1, 'registro_id': 1}
                with patch('core.views.procesar_publicaciones_con_ia', return_value=resultado), \
                        patch('core.views.fetch_and_store_elterritorio', return_value=resumen_ingesta):
                    respuestas = [
                        (self.client.post('/procesar-ia/'), 'mensaje', False),
                        (self.api.post('/api/publicaciones/ingestar/misiones/'), 'mensaje_ia', True),
                    ]
                request = RequestFactory().post('/alternativa/')
                request.user = self.usuario
                with patch('core.services.gemini_cliente.procesar_publicaciones_con_ia', return_value=resultado), \
                        patch('core.services.gemini_cliente.fetch_and_store_elterritorio', return_value=resumen_ingesta):
                    respuestas.append((alternativa(request, 'misiones'), 'mensaje_ia', True))
                for respuesta, campo, ingesta in respuestas:
                    data = json.loads(respuesta.content)
                    self.assertEqual(respuesta.status_code, codigo)
                    self.assertEqual(data['status'], status_cuerpo)
                    self.assertEqual(data[campo], resultado['mensaje'])
                    self.assertEqual(data['resultado_ia'], resultado)
                    if estado == 'NO_DISPONIBLE':
                        self.assertEqual(data['resultado_ia']['errores'][0]['codigo'],
                                         'servicio_no_disponible')
                    if ingesta:
                        self.assertEqual(data['mensaje_ingesta'], resumen_ingesta)

    def test_fallo_ia_conserva_ingesta_realizada(self):
        from django.test import RequestFactory
        from core.services.gemini_cliente import disparar_ingesta as alternativa
        for alternativo in (False, True):
            with self.subTest(alternativo=alternativo):
                def ingestar(categoria):
                    pub = Publicacion.objects.create(hash_origen=f'ingesta-conservada-{alternativo}', contenido='Texto')
                    return {'status': 'EXITO', 'capturados': 1, 'registro_id': pub.pk}
                destino = 'core.services.gemini_cliente' if alternativo else 'core.views'
                with patch(destino + '.fetch_and_store_elterritorio', side_effect=ingestar), \
                        patch(destino + '.procesar_publicaciones_con_ia', return_value=resultado_ia_simulado('FALLO')):
                    if alternativo:
                        request = RequestFactory().post('/alternativa/')
                        request.user = self.usuario
                        respuesta = alternativa(request, 'misiones')
                    else:
                        respuesta = self.api.post('/api/publicaciones/ingestar/misiones/')
                self.assertEqual(respuesta.status_code, 500)
                self.assertTrue(Publicacion.objects.filter(hash_origen=f'ingesta-conservada-{alternativo}').exists())

    def test_alternativo_corta_ante_error_ingesta(self):
        from django.test import RequestFactory
        from core.services.gemini_cliente import disparar_ingesta as alternativa
        request = RequestFactory().post('/alternativa/')
        request.user = self.usuario
        with patch('core.services.gemini_cliente.fetch_and_store_elterritorio', return_value={'status': 'ERROR'}), \
                patch('core.services.gemini_cliente.procesar_publicaciones_con_ia') as ia:
            self.assertEqual(alternativa(request, 'misiones').status_code, 500)
        ia.assert_not_called()

    def test_cinco_estados_en_comando_y_rechazo_de_cadenas(self):
        for estado in ('EXITO', 'PARCIAL', 'FALLO', 'NO_DISPONIBLE', 'SIN_PENDIENTES'):
            with self.subTest(estado=estado), patch(
                    'core.management.commands.run_pipeline.fetch_and_store_elterritorio',
                    return_value={'status': 'EXITO', 'capturados': 0}), patch(
                    'core.management.commands.run_pipeline.procesar_publicaciones_con_ia',
                    return_value=resultado_ia_simulado(estado)):
                salida = StringIO()
                if estado in ('EXITO', 'SIN_PENDIENTES'):
                    call_command('run_pipeline', stdout=salida)
                    self.assertIn('Pipeline completado exitosamente.', salida.getvalue())
                else:
                    with self.assertRaises(CommandError):
                        call_command('run_pipeline', stdout=salida)
                    self.assertNotIn('Pipeline completado exitosamente.', salida.getvalue())
                self.assertIn('Resumen IA de prueba.', salida.getvalue())
        with patch('core.management.commands.run_pipeline.fetch_and_store_elterritorio',
                   return_value={'status': 'EXITO'}), patch(
                'core.management.commands.run_pipeline.procesar_publicaciones_con_ia', return_value='Procesado'):
            with self.assertRaisesMessage(CommandError, 'Resultado de IA inválido'):
                call_command('run_pipeline', stdout=StringIO())
        with patch('core.views.procesar_publicaciones_con_ia', return_value='Procesado'):
            with self.assertRaises(TypeError):
                self.client.post('/procesar-ia/')
