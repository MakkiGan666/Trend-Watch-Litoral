"""Motor de IA configurable: Gemini, Ollama, respaldo automático y panel de administración.

Sin red: Gemini es un Mock con las clases de error reales del SDK y Ollama se simula con
`httpx.MockTransport`. Ninguna prueba toca Google ni un Ollama instalado.
"""
import json
import os
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from google.genai import errors as genai_errors

from core.models import ConfiguracionIA, Locacion, Publicacion, Sentimiento
from core.services.clasificacion import clasificar_lote
from core.services.gemini_cliente import GeminiCliente
from core.services.ia.base import (
    ESTADO_CONECTADO, ESTADO_DESCONECTADO, ESTADO_ERROR_CONEXION, ESTADO_NO_CONFIGURADO,
    ErrorProveedor, Solicitud,
)
from core.services.ia.gestor import GestorIA, configuracion_actual
from core.services.ia.ollama import ProveedorOllama, config_ollama

User = get_user_model()
CLAVE = 'clave-ficticia-test'
TITULO = 'TITULO-NO-DEBE-LOGUEARSE'
GEMINI_JSON = json.dumps({'polaridad': 0.5, 'confianza': 0.8, 'localidades': [
    {'nombre': 'Posadas', 'latitud': -27.36, 'longitud': -55.89}]})
LOGGER_GESTOR = 'core.services.ia.gestor'


def solicitud(**kwargs):
    return Solicitud(system='sistema', contenido='contenido', tarea='prueba', **kwargs)


def error_gemini_503():
    return genai_errors.ServerError(503, {'error': {'code': 503, 'status': 'UNAVAILABLE', 'message': 'alta demanda'}})


def error_gemini_401():
    return genai_errors.ClientError(401, {'error': {'code': 401, 'status': 'UNAUTHENTICATED', 'message': 'clave invalida'}})


class OllamaSimulado:
    """Servidor Ollama falso: registra los pedidos y responde según `modo`."""

    def __init__(self, contenido='{"ok": true}', modo='ok', modelos=('llama3.1:latest',)):
        self.contenido, self.modo, self.modelos = contenido, modo, modelos
        self.pedidos = []
        self.proveedor = ProveedorOllama(cliente_http=httpx.Client(transport=httpx.MockTransport(self._atender)))

    def _atender(self, request):
        self.pedidos.append(request)
        if self.modo == 'caido':
            raise httpx.ConnectError('sin conexión', request=request)
        if self.modo == 'timeout':
            raise httpx.ReadTimeout('lento', request=request)
        if self.modo == '503':
            return httpx.Response(503)
        if self.modo == '400':
            return httpx.Response(400)
        if request.url.path == '/api/tags':
            return httpx.Response(200, json={'models': [{'name': n} for n in self.modelos]})
        return httpx.Response(200, json={'message': {'role': 'assistant', 'content': self.contenido}})

    @property
    def generaciones(self):
        return [p for p in self.pedidos if p.url.path == '/api/chat']


class BaseMotorIA(TestCase):
    def setUp(self):
        # Cliente Gemini simulado y Ollama simulado, reemplazados donde los resuelve el gestor.
        self.gemini = SimpleNamespace(client=MagicMock(), types=MagicMock(), model_name='gemini-test')
        self.gemini.client.models.generate_content.return_value = SimpleNamespace(text='{"de": "gemini"}')
        self.ollama = OllamaSimulado(contenido='{"de": "ollama"}')
        for parche in (patch('core.services.gemini_cliente.gemini_cliente', self.gemini),
                       patch('core.services.ia.gestor.ProveedorOllama', return_value=self.ollama.proveedor)):
            parche.start()
            self.addCleanup(parche.stop)

    def configurar(self, principal='gemini', respaldo=True):
        ConfiguracionIA.objects.update_or_create(
            pk=ConfiguracionIA.PK, defaults={'motor_principal': principal, 'respaldo_automatico': respaldo})

    @property
    def llamadas_gemini(self):
        return self.gemini.client.models.generate_content.call_count


class ProveedoresTests(BaseMotorIA):
    def test_1_gemini_funciona(self):
        self.configurar('gemini')
        respuesta = GestorIA().generar(solicitud())
        self.assertEqual((respuesta.proveedor, respuesta.texto, respuesta.respaldo), ('gemini', '{"de": "gemini"}', False))
        self.assertEqual(self.llamadas_gemini, 1)
        self.assertEqual(self.ollama.pedidos, [])
        kwargs = self.gemini.client.models.generate_content.call_args.kwargs
        self.assertEqual((kwargs['model'], kwargs['contents']), ('gemini-test', 'contenido'))

    def test_2_ollama_funciona_con_el_modelo_local_y_sin_descargar_nada(self):
        self.configurar('ollama')
        respuesta = GestorIA().generar(solicitud())
        self.assertEqual((respuesta.proveedor, respuesta.modelo, respuesta.texto),
                         ('ollama', 'llama3.1:latest', '{"de": "ollama"}'))
        self.assertEqual(self.llamadas_gemini, 0)
        (pedido,) = self.ollama.generaciones
        carga = json.loads(pedido.content)
        self.assertEqual(carga['model'], 'llama3.1:latest')
        self.assertIs(carga['stream'], False)
        self.assertEqual(carga['format'], 'json')
        self.assertEqual([m['role'] for m in carga['messages']], ['system', 'user'])
        self.assertFalse([p for p in self.ollama.pedidos if 'pull' in p.url.path])

    def test_3_gemini_falla_y_se_activa_llama(self):
        self.configurar('gemini', respaldo=True)
        self.gemini.client.models.generate_content.side_effect = error_gemini_503()
        with self.assertLogs(LOGGER_GESTOR, 'INFO') as logs:
            respuesta = GestorIA().generar(solicitud(referencia=7))
        self.assertEqual((respuesta.proveedor, respuesta.respaldo), ('ollama', True))
        self.assertEqual((self.llamadas_gemini, len(self.ollama.generaciones)), (1, 1))
        salida = '\n'.join(logs.output)
        self.assertIn('cambio de motor tarea=prueba de=gemini a=ollama motivo=no_disponible referencia=7', salida)
        self.assertIn('proveedor=ollama modelo=llama3.1:latest respaldo=si', salida)
        fila = ConfiguracionIA.objects.get(pk=ConfiguracionIA.PK)
        self.assertIsNotNone(fila.ultimo_respaldo_en)
        self.assertEqual(fila.ultimo_respaldo_detalle, 'gemini → ollama (no_disponible)')

    def test_3b_timeout_y_conexion_de_gemini_tambien_activan_el_respaldo(self):
        self.configurar('gemini')
        for error in (httpx.ReadTimeout('lento'), httpx.ConnectError('caído')):
            with self.subTest(error=type(error).__name__):
                self.gemini.client.models.generate_content.side_effect = error
                self.assertEqual(GestorIA().generar(solicitud()).proveedor, 'ollama')

    def test_4_ollama_falla_y_se_activa_gemini(self):
        self.configurar('ollama', respaldo=True)
        for modo in ('caido', 'timeout', '503'):
            with self.subTest(modo=modo):
                self.ollama.modo = modo
                self.gemini.client.models.generate_content.reset_mock()
                respuesta = GestorIA().generar(solicitud())
                self.assertEqual((respuesta.proveedor, respuesta.respaldo), ('gemini', True))
                self.assertEqual(self.llamadas_gemini, 1)

    def test_5_con_el_respaldo_desactivado_no_cambia_de_proveedor(self):
        self.configurar('gemini', respaldo=False)
        error = error_gemini_503()
        self.gemini.client.models.generate_content.side_effect = error
        with self.assertRaises(genai_errors.ServerError) as contexto:
            GestorIA().generar(solicitud())
        self.assertIs(contexto.exception, error)
        self.assertEqual(self.ollama.pedidos, [])
        self.configurar('ollama', respaldo=False)
        self.ollama.modo = 'caido'
        self.gemini.client.models.generate_content.reset_mock()
        with self.assertRaises(ErrorProveedor):
            GestorIA().generar(solicitud())
        self.assertEqual(self.llamadas_gemini, 0)

    def test_errores_no_temporales_no_usan_el_respaldo(self):
        self.configurar('gemini', respaldo=True)
        self.gemini.client.models.generate_content.side_effect = error_gemini_401()
        with self.assertRaises(genai_errors.ClientError):
            GestorIA().generar(solicitud())
        self.assertEqual(self.ollama.pedidos, [])
        self.configurar('ollama', respaldo=True)
        self.ollama.modo = '400'
        with self.assertRaises(ErrorProveedor) as contexto:
            GestorIA().generar(solicitud())
        self.assertEqual(contexto.exception.codigo, 'solicitud_rechazada')
        self.assertEqual(self.llamadas_gemini, 1)  # sólo la del caso anterior

    def test_validacion_de_la_respuesta_no_activa_el_respaldo(self):
        self.configurar('ollama', respaldo=True)
        self.ollama.contenido = '   '
        with self.assertRaises(ErrorProveedor) as contexto:
            GestorIA().generar(solicitud())
        self.assertEqual(contexto.exception.codigo, 'respuesta_invalida')
        self.assertEqual(self.llamadas_gemini, 0)

    def test_6_ambos_proveedores_desconectados(self):
        self.configurar('gemini', respaldo=True)
        self.gemini.client.models.generate_content.side_effect = error_gemini_503()
        self.ollama.modo = 'caido'
        with self.assertLogs(LOGGER_GESTOR, 'WARNING') as logs, self.assertRaises(ErrorProveedor):
            GestorIA().generar(solicitud())
        # Un único intento por proveedor: sin bucles ni solicitudes duplicadas.
        self.assertEqual((self.llamadas_gemini, len(self.ollama.generaciones)), (1, 1))
        self.assertIn('ambos motores fallaron principal=gemini(no_disponible) respaldo=ollama(sin_conexion)',
                      '\n'.join(logs.output))

    def test_respaldo_no_configurado_se_informa_sin_intentarlo(self):
        self.configurar('ollama', respaldo=True)
        self.ollama.modo = 'caido'
        self.gemini.client = None  # sin GEMINI_API_KEY
        with self.assertRaises(ErrorProveedor):
            GestorIA().generar(solicitud())
        self.assertEqual(len(self.ollama.generaciones), 1)

    def test_valores_por_defecto_sin_configuracion(self):
        configuracion = configuracion_actual()
        self.assertEqual((configuracion.principal, configuracion.respaldo_automatico), ('gemini', True))
        self.assertEqual(configuracion.alternativo, 'ollama')

    def test_ollama_desenvuelve_listas_y_respeta_la_direccion_configurada(self):
        self.configurar('ollama')
        self.ollama.contenido = '{"resultados": [{"indice": 1}]}'
        self.assertEqual(GestorIA().generar(solicitud(esperado='lista')).texto, '[{"indice": 1}]')
        self.assertEqual(GestorIA().generar(solicitud(esperado='objeto')).texto, '{"resultados": [{"indice": 1}]}')
        # Un único elemento suelto se convierte en lista; una forma irreconocible queda intacta.
        self.ollama.contenido = '{"indice": 0, "categoria": "Política"}'
        self.assertEqual(GestorIA().generar(solicitud(esperado='lista')).texto, '[{"indice": 0, "categoria": "Política"}]')
        self.ollama.contenido = '{"a": [1], "b": [2]}'
        self.assertEqual(GestorIA().generar(solicitud(esperado='lista')).texto, '{"a": [1], "b": [2]}')
        self.assertIn('arreglo JSON', json.loads(self.ollama.generaciones[0].content)['messages'][0]['content'])
        self.assertNotIn('arreglo JSON', json.loads(self.ollama.generaciones[1].content)['messages'][0]['content'])
        self.ollama.contenido = '{"resultados": [{"indice": 1}]}'
        with patch.dict(os.environ, {'OLLAMA_BASE_URL': 'http://host.docker.internal:11434/',
                                     'OLLAMA_MODELO_CHAT': 'otro:1b', 'OLLAMA_TIMEOUT': 'x'}):
            self.assertEqual(config_ollama(), ('http://host.docker.internal:11434', 'otro:1b', 60.0))
            GestorIA().generar(solicitud())
        self.assertEqual(str(self.ollama.generaciones[-1].url), 'http://host.docker.internal:11434/api/chat')

    def test_direccion_invalida_es_error_de_configuracion_sin_respaldo(self):
        self.configurar('ollama', respaldo=True)
        with patch.dict(os.environ, {'OLLAMA_BASE_URL': 'file:///etc/passwd'}):
            with self.assertRaises(ErrorProveedor) as contexto:
                GestorIA().generar(solicitud())
        self.assertEqual(contexto.exception.codigo, 'configuracion_invalida')
        self.assertEqual((self.ollama.pedidos, self.llamadas_gemini), ([], 0))


class EstadoDeConexionTests(BaseMotorIA):
    def test_ollama_estados(self):
        self.assertEqual(self.ollama.proveedor.probar_conexion().estado, ESTADO_CONECTADO)
        self.ollama.modelos = ('gemma2:latest',)
        sin_modelo = self.ollama.proveedor.probar_conexion()
        self.assertEqual(sin_modelo.estado, ESTADO_ERROR_CONEXION)
        self.assertIn('no está instalado', sin_modelo.detalle)
        self.assertFalse([p for p in self.ollama.pedidos if 'pull' in p.url.path])
        for modo in ('caido', 'timeout', '503'):
            self.ollama.modo = modo
            self.assertEqual(self.ollama.proveedor.probar_conexion().estado, ESTADO_DESCONECTADO)
        self.ollama.modo = '400'
        self.assertEqual(self.ollama.proveedor.probar_conexion().estado, ESTADO_ERROR_CONEXION)

    def test_gemini_estados_sin_ejecutar_un_analisis(self):
        proveedor = GestorIA().proveedor('gemini')
        self.assertEqual(proveedor.probar_conexion().estado, ESTADO_CONECTADO)
        self.gemini.client.models.generate_content.assert_not_called()
        self.gemini.client.models.get.assert_called_once_with(model='gemini-test')
        self.gemini.client.models.get.side_effect = httpx.ConnectError('caído')
        self.assertEqual(proveedor.probar_conexion().estado, ESTADO_DESCONECTADO)
        self.gemini.client.models.get.side_effect = error_gemini_401()
        estado = proveedor.probar_conexion()
        self.assertEqual(estado.estado, ESTADO_ERROR_CONEXION)
        self.assertNotIn('invalida', estado.detalle)  # nunca se muestra el mensaje del proveedor
        self.gemini.client = None
        self.assertEqual(proveedor.probar_conexion().estado, ESTADO_NO_CONFIGURADO)


class CapacidadDeGeneracionTests(BaseMotorIA):
    """«Conectado» (servicio responde) no equivale a «puede generar»."""

    def test_ollama(self):
        proveedor = self.ollama.proveedor
        estado = proveedor.probar_generacion()
        self.assertEqual((estado.estado, estado.detalle), (ESTADO_CONECTADO, 'Generó una respuesta de prueba correctamente.'))
        carga = json.loads(self.ollama.generaciones[-1].content)
        self.assertEqual(carga['messages'][1]['content'], 'ping')  # pedido fijo, sin datos de noticias
        for modo, esperado in (('caido', ESTADO_DESCONECTADO), ('timeout', ESTADO_DESCONECTADO),
                               ('503', ESTADO_DESCONECTADO), ('400', ESTADO_ERROR_CONEXION)):
            self.ollama.modo = modo
            self.assertEqual(proveedor.probar_generacion().estado, esperado, modo)
        self.ollama.modo, self.ollama.contenido = 'ok', '  '
        self.assertEqual(proveedor.probar_generacion().estado, ESTADO_ERROR_CONEXION)

    def test_gemini_conectado_pero_sin_capacidad_de_generar(self):
        proveedor = GestorIA().proveedor('gemini')
        self.gemini.client.models.generate_content.side_effect = error_gemini_503()
        self.assertEqual(proveedor.probar_conexion().estado, ESTADO_CONECTADO)  # metadatos: responde
        estado = proveedor.probar_generacion()                                  # generación: no
        self.assertEqual(estado.estado, ESTADO_DESCONECTADO)
        self.assertIn('no_disponible', estado.detalle)
        self.assertNotIn('alta demanda', estado.detalle)  # sin mensajes del proveedor
        self.gemini.client.models.generate_content.side_effect = error_gemini_401()
        self.assertEqual(proveedor.probar_generacion().estado, ESTADO_ERROR_CONEXION)
        self.gemini.client.models.generate_content.side_effect = None
        self.assertEqual(proveedor.probar_generacion().estado, ESTADO_CONECTADO)
        self.gemini.client = None
        self.assertEqual(proveedor.probar_generacion().estado, ESTADO_NO_CONFIGURADO)

    def test_la_prueba_no_usa_respaldo_ni_guarda_nada(self):
        self.configurar('gemini', respaldo=True)
        self.gemini.client.models.generate_content.side_effect = error_gemini_503()
        before = ConfiguracionIA.objects.get(pk=ConfiguracionIA.PK).ultimo_respaldo_en
        self.assertEqual(GestorIA().proveedor('gemini').probar_generacion().estado, ESTADO_DESCONECTADO)
        self.assertEqual(self.ollama.pedidos, [])
        self.assertEqual(ConfiguracionIA.objects.get(pk=ConfiguracionIA.PK).ultimo_respaldo_en, before)
        self.assertFalse(Sentimiento.objects.exists() or Locacion.objects.exists())


class ServiciosConMotorElegidoTests(BaseMotorIA):
    """9: los servicios mantienen su formato de respuesta con cualquiera de los dos motores."""

    def setUp(self):
        super().setUp()
        self.cliente = GeminiCliente(api_key=CLAVE)
        self.cliente.client, self.cliente.types = self.gemini.client, self.gemini.types
        parche = patch('core.services.gemini_cliente.time.sleep')
        parche.start()
        self.addCleanup(parche.stop)
        self.pub = Publicacion.objects.create(hash_origen='motor-ia', titulo=TITULO, contenido='Texto en Posadas')

    def assertNadaPersistido(self):
        self.assertFalse(Sentimiento.objects.exists())
        self.assertFalse(Locacion.objects.exists())
        self.pub.refresh_from_db()
        self.assertFalse(self.pub.procesado_ia)

    def test_ollama_como_motor_principal_no_persiste_ni_siquiera_se_consulta(self):
        self.ollama.contenido = GEMINI_JSON  # respuesta perfectamente válida: igual no se guarda
        for respaldo in (True, False):
            with self.subTest(respaldo=respaldo):
                self.configurar('ollama', respaldo=respaldo)
                with self.assertLogs('core.services.gemini_cliente', 'WARNING') as logs:
                    resultado = self.cliente.procesar_pendientes(batch_size=1)
                self.assertEqual((resultado['estado'], resultado['procesadas']), ('NO_DISPONIBLE', 0))
                self.assertEqual(resultado['errores'], [{'id_publicacion_api': self.pub.pk, 'codigo': 'motor_no_persistente'}])
                self.assertIn('codigo=motor_no_persistente proveedor=ollama', '\n'.join(logs.output))
                self.assertNadaPersistido()
        # No se gasta una generación que se descartaría, ni se llama a Gemini.
        self.assertEqual((len(self.ollama.generaciones), self.llamadas_gemini), (0, 0))

    def test_guardia_final_descarta_cualquier_resultado_de_un_proveedor_no_persistible(self):
        from core.services.ia.base import RespuestaIA
        self.configurar('gemini', respaldo=True)
        for proveedor, respaldo, codigo in (('ollama', False, 'motor_no_persistente'),
                                            ('ollama', True, 'respaldo_no_persistido'),
                                            ('desconocido', False, 'motor_no_persistente')):
            with self.subTest(proveedor=proveedor, respaldo=respaldo), \
                    patch.object(GestorIA, 'generar',
                                 return_value=RespuestaIA(GEMINI_JSON, proveedor, 'modelo', respaldo=respaldo)):
                resultado = self.cliente.procesar_pendientes(batch_size=1)
                self.assertEqual(resultado['errores'][0]['codigo'], codigo)
                self.assertNadaPersistido()

    def test_gemini_conserva_la_persistencia_con_el_respaldo_activo_o_no(self):
        for respaldo in (True, False):
            with self.subTest(respaldo=respaldo):
                self.pub.procesado_ia = False
                self.pub.save(update_fields=['procesado_ia'])
                Sentimiento.objects.all().delete()
                Locacion.objects.all().delete()
                self.configurar('gemini', respaldo=respaldo)
                self.gemini.client.models.generate_content.return_value = SimpleNamespace(text=GEMINI_JSON)
                resultado = self.cliente.procesar_pendientes(batch_size=1)
                self.assertEqual((resultado['estado'], resultado['procesadas']), ('EXITO', 1))
                self.pub.refresh_from_db()
                self.assertTrue(self.pub.procesado_ia)
                sentimiento = Sentimiento.objects.get(id_publicacion_api=self.pub)
                self.assertEqual((sentimiento.polaridad, sentimiento.confianza), (0.5, 0.8))
                self.assertEqual(Locacion.objects.get(id_publicacion_api=self.pub).location, 'Posadas')
        self.assertEqual(self.ollama.pedidos, [])

    def test_capacidad_de_persistir_es_propia_del_proveedor(self):
        gestor = GestorIA()
        self.assertTrue(gestor.persiste_analisis_publicaciones('gemini'))
        self.assertFalse(gestor.persiste_analisis_publicaciones('ollama'))
        self.assertFalse(gestor.persiste_analisis_publicaciones('otro'))

    def test_resultado_de_respaldo_no_se_guarda_y_la_noticia_sigue_pendiente(self):
        self.configurar('gemini', respaldo=True)
        self.gemini.client.models.generate_content.side_effect = httpx.ConnectError('caído')
        self.ollama.contenido = GEMINI_JSON  # válido: aun así no debe persistirse
        with self.assertLogs('core.services.gemini_cliente', 'WARNING') as logs:
            resultado = self.cliente.procesar_pendientes(batch_size=1)
        self.assertEqual((resultado['estado'], resultado['procesadas']), ('FALLO', 0))
        self.assertEqual(resultado['errores'][0]['codigo'], 'respaldo_no_persistido')
        self.assertIn('codigo=respaldo_no_persistido proveedor=ollama', '\n'.join(logs.output))
        self.assertEqual(len(self.ollama.generaciones), 1)  # el respaldo sí se intentó
        self.assertFalse(Sentimiento.objects.exists() or Locacion.objects.exists())
        self.pub.refresh_from_db()
        self.assertFalse(self.pub.procesado_ia)

    def test_rango_de_fechas_solo_selecciona_publicaciones_del_periodo(self):
        from datetime import date, datetime, timezone as tz
        Publicacion.objects.filter(pk=self.pub.pk).update(fecha_publicacion=datetime(2026, 11, 4, 12, tzinfo=tz.utc))
        fuera = Publicacion.objects.create(hash_origen='fuera', contenido='x',
                                           fecha_publicacion=datetime(2026, 10, 20, 12, tzinfo=tz.utc))
        self.configurar('gemini')
        self.gemini.client.models.generate_content.return_value = SimpleNamespace(text=GEMINI_JSON)
        resultado = self.cliente.procesar_pendientes(batch_size=5, desde=date(2026, 11, 3), hasta=date(2026, 11, 7))
        self.assertEqual((resultado['seleccionadas'], resultado['procesadas']), (1, 1))
        fuera.refresh_from_db()
        self.assertFalse(fuera.procesado_ia)
        self.assertFalse(Sentimiento.objects.filter(id_publicacion_api=fuera).exists())

    def test_sin_clave_de_gemini_cada_configuracion_informa_su_motivo(self):
        self.cliente.client = None
        self.ollama.contenido = GEMINI_JSON
        self.configurar('ollama')
        self.assertEqual(self.cliente.procesar_pendientes(batch_size=1)['errores'][0]['codigo'], 'motor_no_persistente')
        self.configurar('gemini')  # principal sin clave: no hay motor disponible, no se salta a Ollama
        resultado = self.cliente.procesar_pendientes(batch_size=1)
        self.assertEqual((resultado['estado'], resultado['errores'][0]['codigo']),
                         ('NO_DISPONIBLE', 'servicio_no_disponible'))
        self.assertEqual(self.ollama.pedidos, [])
        self.assertNadaPersistido()

    def test_clasificacion_con_ollama_acepta_la_lista_envuelta(self):
        self.configurar('ollama')
        self.ollama.contenido = '{"clasificacion": [{"indice": 0, "categoria": "Política"}]}'
        resultado = clasificar_lote([{'titulo': 'Nota nacional', 'contenido': 'Sin localidad', 'seccion': 'pais-y-mundo'}])
        self.assertEqual((resultado[0]['categoria'], resultado[0]['metodo']), ('Política', 'ia'))
        self.assertEqual(self.llamadas_gemini, 0)

    def test_revision_de_departamentos_sigue_funcionando_con_ollama(self):
        from core.services.clasificacion_departamentos import consultar_ia
        noticia = Publicacion.objects.create(
            hash_origen='wanda', titulo='Llegaron equipamientos', departamento='',
            contenido='Wanda recibió nuevos equipos para el centro cultural.')
        self.configurar('ollama')
        self.ollama.contenido = json.dumps([{
            'id': noticia.pk, 'estado': 'asignado', 'departamento': 'iguazu',
            'lugar': 'Wanda', 'evidencia': 'Wanda recibió nuevos equipos'}])
        cliente = SimpleNamespace(client=self.gemini.client, types=self.gemini.types, model_name='gemini-test')
        decisiones, errores = consultar_ia([noticia], cliente=cliente)
        self.assertEqual((decisiones[noticia.pk]['departamento'], errores), ('iguazu', {}))
        self.assertEqual(cliente.modelo_utilizado, 'ollama:llama3.1:latest')
        self.assertEqual(self.llamadas_gemini, 0)

    def test_10_errores_quedan_registrados_sin_datos_sensibles(self):
        self.configurar('gemini', respaldo=True)
        self.gemini.client.models.generate_content.side_effect = error_gemini_503()
        self.ollama.modo = 'caido'
        with self.assertLogs('core.services', 'INFO') as logs:
            resultado = self.cliente.procesar_pendientes(batch_size=1)
        salida = '\n'.join(logs.output)
        self.assertEqual(resultado['errores'][0]['codigo'], 'llamada_gemini')
        self.assertIn('IA: cambio de motor tarea=analisis_publicacion de=gemini a=ollama', salida)
        self.assertIn('ambos motores fallaron', salida)
        for secreto in (CLAVE, TITULO, 'Texto en Posadas'):
            self.assertNotIn(secreto, salida)


class PanelMotorIATests(BaseMotorIA):
    @classmethod
    def setUpTestData(cls):
        call_command('configurar_roles', stdout=StringIO())
        cls.admin = User.objects.create_user('juan', is_staff=True)
        cls.admin.groups.add(Group.objects.get(name='Administrador'))
        cls.root = User.objects.create_superuser('root')
        cls.lector = User.objects.create_user('lector')
        cls.staff_sin_rol = User.objects.create_user('staff', is_staff=True)
        cls.url = reverse('motor_ia')

    def test_8_sin_permisos_no_puede_ver_ni_modificar_ni_probar(self):
        self.configurar('gemini', respaldo=True)
        envio = {'motor_principal': 'ollama'}
        for usuario, esperado in ((None, 302), (self.lector, 403), (self.staff_sin_rol, 403)):
            with self.subTest(usuario=usuario):
                self.client.logout()
                if usuario:
                    self.client.force_login(usuario)
                self.assertEqual(self.client.get(self.url).status_code, esperado)
                self.assertEqual(self.client.post(self.url, envio).status_code, esperado)
                self.assertEqual(self.client.post(reverse('probar_motor_ia', args=['ollama'])).status_code, esperado)
        fila = ConfiguracionIA.objects.get(pk=ConfiguracionIA.PK)
        self.assertEqual((fila.motor_principal, fila.respaldo_automatico), ('gemini', True))
        self.assertEqual(self.ollama.pedidos, [])

    def test_7_la_configuracion_persiste_tras_reiniciar(self):
        for usuario in (self.admin, self.root):
            self.client.force_login(usuario)
            respuesta = self.client.post(self.url, {'motor_principal': 'ollama'})  # casilla ausente = desactivado
            self.assertRedirects(respuesta, self.url)
            # «Reinicio»: nuevo gestor y nueva lectura desde la base, sin estado en memoria.
            configuracion = configuracion_actual()
            self.assertEqual((configuracion.principal, configuracion.respaldo_automatico), ('ollama', False))
            self.client.post(self.url, {'motor_principal': 'gemini', 'respaldo_automatico': 'on'})
            self.assertEqual(GestorIA().principal().nombre, 'gemini')
            self.assertTrue(configuracion_actual().respaldo_automatico)
        fila = ConfiguracionIA.objects.get(pk=ConfiguracionIA.PK)
        self.assertEqual(fila.actualizado_por, self.root)
        self.assertEqual(ConfiguracionIA.objects.count(), 1)
        self.assertTrue(LogEntry.objects.filter(change_message__startswith='Motor de IA:').exists())

    def test_pagina_refleja_la_configuracion_y_el_menu_esta_bajo_usuarios_registrados(self):
        self.configurar('ollama', respaldo=False)
        self.client.force_login(self.admin)
        html = self.client.get(self.url).content.decode()
        self.assertIn('Motor de inteligencia artificial', html)
        self.assertRegex(html, r'value="ollama" checked')
        self.assertNotRegex(html, r'name="respaldo_automatico"\s+checked')
        self.assertIn('Estado del respaldo automático: <strong>desactivado</strong>', html)
        self.assertLess(html.index('>Usuarios registrados<'), html.index('>Motor de Inteligencia Artificial<'))
        listado = self.client.get(reverse('listado_usuarios')).content.decode()
        self.assertIn(self.url, listado)

    def test_valida_la_eleccion_del_motor(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(self.url, {'motor_principal': 'otro'}).status_code, 200)
        self.assertEqual(self.client.post(self.url, {}).status_code, 200)
        self.gemini.client = None  # Gemini sin clave no puede ser el principal
        respuesta = self.client.post(self.url, {'motor_principal': 'gemini'})
        self.assertContains(respuesta, 'falta GEMINI_API_KEY')
        self.assertFalse(ConfiguracionIA.objects.exists())

    def test_probar_conexion_devuelve_estado_sin_datos_sensibles(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('probar_motor_ia', args=['ollama'])).status_code, 405)
        self.assertEqual(self.client.post(reverse('probar_motor_ia', args=['otro'])).status_code, 404)
        datos = self.client.post(reverse('probar_motor_ia', args=['ollama'])).json()
        self.assertEqual((datos['estado'], datos['etiqueta'], datos['modelo']),
                         ('conectado', 'Conectado', 'llama3.1:latest'))
        self.ollama.modo = 'caido'
        self.assertEqual(self.client.post(reverse('probar_motor_ia', args=['ollama'])).json()['estado'], 'desconectado')
        generar = self.gemini.client.models.generate_content
        self.gemini.client = None
        gemini = self.client.post(reverse('probar_motor_ia', args=['gemini'])).json()
        self.assertEqual(gemini['estado'], 'no_configurado')
        self.assertNotIn(CLAVE, json.dumps(gemini))
        generar.assert_not_called()

    def test_probar_generacion_en_el_panel_distingue_conexion_y_generacion(self):
        self.client.force_login(self.admin)
        url = reverse('probar_motor_ia', args=['gemini'])
        self.gemini.client.models.generate_content.side_effect = error_gemini_503()
        conexion = self.client.post(url, {'alcance': 'conexion'}).json()
        generacion = self.client.post(url, {'alcance': 'generacion'}).json()
        self.assertEqual((conexion['alcance'], conexion['estado']), ('conexion', 'conectado'))
        self.assertEqual((generacion['alcance'], generacion['estado']), ('generacion', 'desconectado'))
        self.assertEqual(self.client.post(url, {'alcance': 'otro'}).status_code, 400)
        self.assertEqual(self.ollama.pedidos, [])  # sin respaldo en las pruebas
        for usuario in (self.lector, self.staff_sin_rol):
            self.client.force_login(usuario)
            self.assertEqual(self.client.post(url, {'alcance': 'generacion'}).status_code, 403)

    def test_pagina_aclara_conexion_generacion_y_que_motor_guarda_analisis(self):
        self.client.force_login(self.admin)
        html = self.client.get(self.url).content.decode()
        self.assertIn('Conexión al servicio', html)
        self.assertIn('Capacidad de generación', html)
        self.assertIn('Probar generación', html)
        self.assertIn('sólo significa que el servicio responde', html)
        self.assertIn('<strong>no se guardan</strong> con este motor', html)  # Llama
        self.assertEqual(html.count('se guardan con este motor'), 1)  # sólo Gemini
