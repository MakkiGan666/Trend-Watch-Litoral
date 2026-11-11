"""Modelo configurable, reintentos y logging de GeminiCliente.

Sin red ni cuota: el cliente de Gemini es un Mock y los errores son las clases
reales del SDK (`google.genai.errors`) construidas con cuerpos de ejemplo.
"""
import json
from unittest.mock import Mock, call, patch

import httpx
from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from google.genai import errors as genai_errors

from core.models import Locacion, Publicacion, Sentimiento
from core.services.clasificacion import clasificar_lote
from core.services.gemini_cliente import (
    LARGO_MAX_MENSAJE, MODELO_POR_DEFECTO, GeminiCliente, mensaje_error_seguro,
)
from core.services.resultado_ia import respuesta_resultado_ia

RPC = 'type.googleapis.com/google.rpc.'
CLAVE = 'clave-ficticia-test'
TITULO = 'TITULO-NO-DEBE-LOGUEARSE'
CONTENIDO = 'CONTENIDO-NO-DEBE-LOGUEARSE'
LOGGER = 'core.services.gemini_cliente'


def error_503():
    return genai_errors.ServerError(503, {'error': {
        'code': 503, 'status': 'UNAVAILABLE', 'message': 'This model is currently experiencing high demand.',
    }})


def error_429(quota_id=None, retry_delay=None):
    detalles = []
    if quota_id:
        detalles.append({'@type': RPC + 'QuotaFailure', 'violations': [{'quotaId': quota_id}]})
    if retry_delay:
        detalles.append({'@type': RPC + 'RetryInfo', 'retryDelay': retry_delay})
    return genai_errors.ClientError(429, {'error': {
        'code': 429, 'status': 'RESOURCE_EXHAUSTED', 'message': 'Quota exceeded.', 'details': detalles,
    }})


MENSAJE_404 = ('models/gemini-2.5-flash is not found for API version v1beta, or is not supported for '
               'generateContent. Call ListModels to see the list of available models and their supported methods.')
CLAVE_GOOGLE = 'AIza' + 'Sy' + 'A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6'


def error_con_mensaje(mensaje, codigo=404, estado='NOT_FOUND'):
    return genai_errors.ClientError(codigo, {'error': {'code': codigo, 'status': estado, 'message': mensaje}})


def cliente_simulado(**kwargs):
    with patch('core.services.gemini_cliente.genai'):
        cliente = GeminiCliente(api_key=CLAVE, **kwargs)
    cliente.client = Mock()
    cliente.types = Mock()
    return cliente


class ModeloConfiguradoTestCase(TestCase):
    @override_settings(GEMINI_MODEL='gemini-2.5-flash')
    def test_usa_el_modelo_de_la_configuracion(self):
        cliente = cliente_simulado()
        self.assertEqual(cliente.model_name, 'gemini-2.5-flash')

    @override_settings(GEMINI_MODEL='')
    def test_variable_vacia_usa_el_modelo_por_defecto(self):
        self.assertEqual(cliente_simulado().model_name, MODELO_POR_DEFECTO)
        self.assertEqual(MODELO_POR_DEFECTO, 'gemini-3.8-flash')

    def test_sin_variable_usa_el_modelo_por_defecto(self):
        with override_settings():
            del settings.GEMINI_MODEL
            self.assertEqual(cliente_simulado().model_name, MODELO_POR_DEFECTO)

    @override_settings(GEMINI_MODEL='gemini-2.5-flash')
    def test_argumento_explicito_tiene_prioridad(self):
        self.assertEqual(cliente_simulado(model_name='otro-modelo').model_name, 'otro-modelo')

    @override_settings(GEMINI_MODEL='gemini-2.5-flash')
    def test_clasificacion_usa_el_modelo_del_cliente_compartido(self):
        cliente = cliente_simulado()
        cliente.client.models.generate_content.return_value.text = json.dumps(
            [{'indice': 0, 'categoria': 'Salud'}],
        )
        with patch('core.services.gemini_cliente.gemini_cliente', cliente):
            resultado = clasificar_lote([{'titulo': 'Nota', 'contenido': 'Texto', 'seccion': ''}])
        self.assertEqual(resultado[0]['metodo'], 'ia')
        self.assertEqual(cliente.client.models.generate_content.call_args.kwargs['model'], 'gemini-2.5-flash')


class ReintentosGeminiTestCase(TestCase):
    def setUp(self):
        self.cliente = cliente_simulado(model_name='modelo-simulado')
        self.generar = self.cliente.client.models.generate_content
        self.respuesta = Mock(text=json.dumps({
            'polaridad': 0.5, 'confianza': 0.8,
            'localidades': [{'nombre': 'Posadas', 'latitud': -27.3, 'longitud': -55.9}],
        }))
        self.generar.return_value = self.respuesta
        self.pub = Publicacion.objects.create(hash_origen='gemini-errores', titulo=TITULO, contenido=CONTENIDO)
        espera = patch('core.services.gemini_cliente.time.sleep')
        self.espera = espera.start()
        self.addCleanup(espera.stop)

    def procesar(self):
        return self.cliente.procesar_publicaciones_con_ia(batch_size=1)

    def assert_fallo_sin_resultados(self, resultado):
        self.assertEqual(resultado['estado'], 'FALLO')
        self.assertEqual(resultado['errores'], [{'id_publicacion_api': self.pub.pk, 'codigo': 'llamada_gemini'}])
        self.pub.refresh_from_db()
        self.assertFalse(self.pub.procesado_ia)
        self.assertFalse(Sentimiento.objects.exists())
        self.assertFalse(Locacion.objects.exists())

    def test_503_se_reintenta_y_luego_procesa(self):
        self.generar.side_effect = [error_503(), self.respuesta]
        resultado = self.procesar()
        self.assertEqual((resultado['estado'], resultado['procesadas']), ('EXITO', 1))
        self.assertEqual(self.generar.call_count, 2)
        # Espera del reintento (2 s) y la pausa existente tras un resultado confirmado (12 s).
        self.assertEqual(self.espera.call_args_list, [call(2), call(12)])
        # El reintento no duplica guardados.
        self.assertEqual(Sentimiento.objects.filter(id_publicacion_api=self.pub).count(), 1)
        self.assertEqual(Locacion.objects.filter(id_publicacion_api=self.pub).count(), 1)

    def test_503_persistente_agota_los_tres_intentos(self):
        self.generar.side_effect = [error_503(), error_503(), error_503()]
        resultado = self.procesar()
        self.assertEqual(self.generar.call_count, 3)
        self.assertEqual(self.espera.call_args_list, [call(2), call(4)])
        self.assert_fallo_sin_resultados(resultado)

    def test_error_de_red_temporal_se_reintenta(self):
        self.generar.side_effect = [httpx.ConnectError('sin conexión'), self.respuesta]
        self.assertEqual(self.procesar()['procesadas'], 1)
        self.assertEqual(self.generar.call_count, 2)

    def test_errores_definitivos_no_se_reintentan(self):
        definitivos = {
            '401': genai_errors.ClientError(401, {'error': {'code': 401, 'status': 'UNAUTHENTICATED'}}),
            '403': genai_errors.ClientError(403, {'error': {'code': 403, 'status': 'PERMISSION_DENIED'}}),
            'clave_invalida': genai_errors.ClientError(400, {'error': {
                'code': 400, 'status': 'INVALID_ARGUMENT', 'message': 'API key not valid.',
                'details': [{'@type': RPC + 'ErrorInfo', 'reason': 'API_KEY_INVALID'}],
            }}),
            'modelo_inexistente': genai_errors.ClientError(404, {'error': {'code': 404, 'status': 'NOT_FOUND'}}),
            'solicitud_invalida': genai_errors.ClientError(400, {'error': {'code': 400, 'status': 'INVALID_ARGUMENT'}}),
            'desconocido': RuntimeError('fallo inesperado'),
        }
        for nombre, error in definitivos.items():
            with self.subTest(nombre):
                self.generar.reset_mock()
                self.espera.reset_mock()
                self.generar.side_effect = error
                resultado = self.procesar()
                self.assertEqual(self.generar.call_count, 1)
                self.espera.assert_not_called()
                self.assert_fallo_sin_resultados(resultado)

    def test_429_por_cuota_diaria_no_se_reintenta(self):
        # Aunque traiga RetryInfo, una cuota diaria agotada no se recupera en segundos.
        self.generar.side_effect = error_429('GenerateRequestsPerDayPerProjectPerModel-FreeTier', '7s')
        resultado = self.procesar()
        self.assertEqual(self.generar.call_count, 1)
        self.espera.assert_not_called()
        self.assert_fallo_sin_resultados(resultado)

    def test_429_sin_retry_info_no_se_reintenta(self):
        self.generar.side_effect = error_429('GenerateRequestsPerMinutePerProjectPerModel-FreeTier')
        self.assert_fallo_sin_resultados(self.procesar())
        self.assertEqual(self.generar.call_count, 1)

    def test_429_con_espera_mayor_a_30_segundos_no_se_reintenta(self):
        self.generar.side_effect = error_429('GenerateRequestsPerMinutePerProjectPerModel-FreeTier', '45s')
        self.assert_fallo_sin_resultados(self.procesar())
        self.assertEqual(self.generar.call_count, 1)

    def test_429_por_minuto_respeta_retry_delay(self):
        self.generar.side_effect = [
            error_429('GenerateRequestsPerMinutePerProjectPerModel-FreeTier', '7s'), self.respuesta,
        ]
        self.assertEqual(self.procesar()['procesadas'], 1)
        self.assertEqual(self.espera.call_args_list, [call(7.0), call(12)])

    def test_contrato_de_respuesta_intacto(self):
        self.generar.side_effect = error_503()
        resultado = self.procesar()
        self.assertEqual(set(resultado), {
            'estado', 'seleccionadas', 'procesadas', 'omitidas', 'fallidas', 'errores', 'mensaje',
        })
        self.assertEqual(
            (resultado['seleccionadas'], resultado['procesadas'], resultado['omitidas'], resultado['fallidas']),
            (1, 0, 0, 1),
        )
        self.assertEqual(resultado['mensaje'], 'Lote IA: 0 procesadas, 0 omitidas y 1 fallidas.')
        data, codigo_http = respuesta_resultado_ia(resultado)
        self.assertEqual((data['status'], codigo_http), ('error', 500))

    def test_log_registra_metadatos_sin_datos_sensibles(self):
        self.generar.side_effect = [error_503(), error_503(), error_503()]
        with self.assertLogs(LOGGER, level='INFO') as logs:
            self.procesar()
        texto = '\n'.join(logs.output)
        for esperado in ('intento=1/3', 'intento=3/3', 'tipo=no_disponible', 'codigo_http=503',
                         'estado=UNAVAILABLE', f'publicacion={self.pub.pk}', 'reintento=si', 'reintento=no',
                         'resultado=fallida codigo=llamada_gemini'):
            self.assertIn(esperado, texto)
        for prohibido in (CLAVE, TITULO, CONTENIDO):
            self.assertNotIn(prohibido, texto)

    def test_log_de_respuesta_invalida_no_incluye_la_respuesta(self):
        self.generar.return_value = Mock(text='{"polaridad": "RESPUESTA-NO-DEBE-LOGUEARSE"}')
        with self.assertLogs(LOGGER, level='INFO') as logs:
            resultado = self.procesar()
        self.assertEqual(resultado['errores'], [{'id_publicacion_api': self.pub.pk, 'codigo': 'validacion_respuesta'}])
        texto = '\n'.join(logs.output)
        self.assertIn('codigo=validacion_respuesta tipo=ValueError', texto)
        for prohibido in ('RESPUESTA-NO-DEBE-LOGUEARSE', CLAVE, TITULO, CONTENIDO):
            self.assertNotIn(prohibido, texto)

    def test_log_de_exito_indica_resultado_final(self):
        with self.assertLogs(LOGGER, level='INFO') as logs:
            self.procesar()
        self.assertIn(f'publicacion={self.pub.pk} resultado=procesada', '\n'.join(logs.output))

    def test_log_incluye_el_mensaje_breve_del_proveedor(self):
        self.generar.side_effect = error_con_mensaje(MENSAJE_404)
        with self.assertLogs(LOGGER, level='INFO') as logs:
            self.procesar()
        intento, final = logs.output
        recortado = MENSAJE_404[:LARGO_MAX_MENSAJE - 1].rstrip() + '…'
        self.assertTrue(intento.startswith('WARNING:'))
        self.assertIn('tipo=modelo_inexistente codigo_http=404 estado=NOT_FOUND reintento=no', intento)
        self.assertIn(f'mensaje="{recortado}"', intento)
        self.assertTrue(final.startswith('ERROR:'))
        self.assertIn(f'resultado=fallida codigo=llamada_gemini tipo=modelo_inexistente mensaje="{recortado}"', final)

    def test_mensaje_con_la_clave_configurada_se_enmascara(self):
        self.generar.side_effect = error_con_mensaje(f'API key {CLAVE} not valid.', 400, 'INVALID_ARGUMENT')
        with self.assertLogs(LOGGER, level='INFO') as logs:
            self.procesar()
        texto = '\n'.join(logs.output)
        self.assertIn('mensaje="API key [oculto] not valid."', texto)
        self.assertNotIn(CLAVE, texto)

    def test_mensaje_que_repite_la_noticia_no_se_registra(self):
        self.generar.side_effect = error_con_mensaje(f'Invalid input near: {CONTENIDO}', 400, 'INVALID_ARGUMENT')
        with self.assertLogs(LOGGER, level='INFO') as logs:
            self.procesar()
        texto = '\n'.join(logs.output)
        self.assertNotIn('mensaje=', texto)
        self.assertNotIn(CONTENIDO, texto)
        # Sin mensaje seguro queda el logging anterior: tipo, código y estado.
        self.assertIn('tipo=error_definitivo codigo_http=400 estado=INVALID_ARGUMENT reintento=no', texto)

    def test_excepcion_ajena_al_sdk_no_registra_su_mensaje(self):
        self.generar.side_effect = RuntimeError(f'fallo con {CLAVE_GOOGLE} y {TITULO}')
        with self.assertLogs(LOGGER, level='INFO') as logs:
            self.procesar()
        texto = '\n'.join(logs.output)
        self.assertNotIn('mensaje=', texto)
        for prohibido in (CLAVE_GOOGLE, TITULO, 'fallo con'):
            self.assertNotIn(prohibido, texto)


class MensajeErrorSeguroTestCase(SimpleTestCase):
    def test_mensaje_corto_se_conserva(self):
        self.assertEqual(mensaje_error_seguro(error_con_mensaje('Model not found.')), 'Model not found.')

    def test_se_limita_a_160_caracteres(self):
        mensaje = mensaje_error_seguro(error_con_mensaje(MENSAJE_404 * 3))
        self.assertLessEqual(len(mensaje), LARGO_MAX_MENSAJE)
        self.assertGreater(len(mensaje), LARGO_MAX_MENSAJE - 10)
        self.assertTrue(mensaje.endswith('…'))

    def test_se_enmascaran_credenciales_y_tokens(self):
        casos = {
            f'Invalid key {CLAVE_GOOGLE} supplied': 'Invalid key [oculto] supplied',
            'Header Authorization: Bearer abc.def-123 rejected': 'Header Authorization: [oculto] rejected',
            'Request to https://x.test/v1?key=SECRETO123 failed': 'Request to https://x.test/v1?[oculto] failed',
            'token=abc123 expired': '[oculto] expired',
            'oauth ya29.a0AfH6SMBx-y_z expired': 'oauth [oculto] expired',
            'opaque ' + 'Q' * 40 + ' value': 'opaque [oculto] value',
        }
        for original, esperado in casos.items():
            with self.subTest(original):
                self.assertEqual(mensaje_error_seguro(error_con_mensaje(original)), esperado)

    def test_se_enmascara_la_clave_configurada_aunque_no_tenga_formato_conocido(self):
        mensaje = mensaje_error_seguro(error_con_mensaje(f'clave {CLAVE} rechazada'), api_key=CLAVE)
        self.assertEqual(mensaje, 'clave [oculto] rechazada')

    def test_enmascara_antes_de_recortar(self):
        # Una clave cortada por el límite no debe quedar parcialmente visible.
        relleno = 'x ' * ((LARGO_MAX_MENSAJE - 10) // 2)
        mensaje = mensaje_error_seguro(error_con_mensaje(relleno + CLAVE_GOOGLE))
        self.assertNotIn('AIza', mensaje)

    def test_mensaje_que_repite_el_prompt_se_descarta(self):
        prompt = 'Título: Corte de luz en Posadas\nContenido: La distribuidora informó un corte programado.'
        error = error_con_mensaje('Bad request: La distribuidora informó un corte programado.')
        self.assertIsNone(mensaje_error_seguro(error, prompt=prompt))
        self.assertEqual(mensaje_error_seguro(error_con_mensaje('Model not found.'), prompt=prompt),
                         'Model not found.')

    def test_espacios_y_caracteres_de_control_se_normalizan(self):
        self.assertEqual(mensaje_error_seguro(error_con_mensaje('linea 1\n\tlinea\x00 2  ')), 'linea 1 linea 2')

    def test_sin_mensaje_seguro_devuelve_none(self):
        self.assertIsNone(mensaje_error_seguro(RuntimeError('cualquier cosa')))
        self.assertIsNone(mensaje_error_seguro(httpx.ConnectError('sin conexión')))
        self.assertIsNone(mensaje_error_seguro(
            genai_errors.ServerError(503, {'error': {'code': 503, 'status': 'UNAVAILABLE'}}),
        ))
        self.assertIsNone(mensaje_error_seguro(error_con_mensaje('   ')))
