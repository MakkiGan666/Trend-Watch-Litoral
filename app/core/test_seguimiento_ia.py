"""Seguimiento centralizado de IA: registro de ejecuciones y panel administrativo.

Todas las llamadas a Gemini y Ollama están simuladas (sin red ni consumo de API).
"""
import json
from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Comentario, EjecucionIA, Publicacion, Sentimiento
from core.services import sentimiento_comentarios
from core.services.clasificacion import clasificar_lote
from core.services.gemini_cliente import GeminiCliente
from core.services.ia import seguimiento
from core.services.ia.base import ErrorProveedor, RespuestaIA, Solicitud
from core.services.ia.gestor import GestorIA
from core.test_motor_ia import GEMINI_JSON, BaseMotorIA, error_gemini_401, error_gemini_503

User = get_user_model()
CLAVE_SECRETA = 'clave-secreta-de-prueba-123456'


def pedido(**datos):
    return Solicitud(system='Instrucciones de prueba', contenido='Texto enviado al modelo',
                     tarea='etiquetado_tematico', **datos)


class RegistroEnGestorTests(BaseMotorIA):
    def setUp(self):
        super().setUp()
        self.pub = Publicacion.objects.create(hash_origen='seg-1', titulo='Noticia', contenido='Texto')

    def test_registra_ejecucion_exitosa_con_entrada_respuesta_y_modelo(self):
        self.configurar('gemini')
        respuesta = GestorIA().generar(pedido(referencia=self.pub.pk, entidad='publicacion'))
        ejecucion = EjecucionIA.objects.get()
        self.assertEqual(respuesta.ejecucion_id, ejecucion.pk)
        self.assertEqual((ejecucion.tarea, ejecucion.proveedor, ejecucion.modelo, ejecucion.estado),
                         ('etiquetado_tematico', 'gemini', 'gemini-test', EjecucionIA.Estado.EXITOSA))
        self.assertEqual(ejecucion.publicacion_id, self.pub.pk)
        self.assertEqual((ejecucion.instrucciones, ejecucion.entrada), ('Instrucciones de prueba', 'Texto enviado al modelo'))
        self.assertEqual(ejecucion.respuesta_original, '{"de": "gemini"}')
        self.assertIsNone(ejecucion.resultado)
        self.assertIsNotNone(ejecucion.duracion_ms)
        self.assertFalse(ejecucion.respaldo)
        self.assertTrue(ejecucion.identificador)

    def test_registra_error_del_proveedor_sin_mensaje_y_relanza(self):
        self.configurar('gemini', respaldo=False)
        self.gemini.client.models.generate_content.side_effect = error_gemini_401()
        with self.assertRaises(Exception):
            GestorIA().generar(pedido())
        ejecucion = EjecucionIA.objects.get()
        self.assertEqual(ejecucion.estado, EjecucionIA.Estado.FALLIDA)
        self.assertEqual(ejecucion.codigo_error, 'autenticacion')
        self.assertEqual(ejecucion.respuesta_original, '')

    def test_distintos_proveedores_y_respaldo_quedan_en_filas_separadas(self):
        self.configurar('gemini', respaldo=True)
        self.gemini.client.models.generate_content.side_effect = error_gemini_503()
        respuesta = GestorIA().generar(pedido())
        self.assertEqual((respuesta.proveedor, respuesta.respaldo), ('ollama', True))
        gemini, ollama = EjecucionIA.objects.order_by('pk')
        self.assertEqual((gemini.proveedor, gemini.estado, gemini.respaldo), ('gemini', 'fallida', False))
        self.assertEqual((ollama.proveedor, ollama.modelo, ollama.estado, ollama.respaldo),
                         ('ollama', 'llama3.1:latest', 'exitosa', True))
        self.assertEqual(ollama.respuesta_original, '{"de": "ollama"}')
        self.assertEqual(respuesta.ejecucion_id, ollama.pk)

    def test_ollama_como_principal(self):
        self.configurar('ollama')
        GestorIA().generar(pedido())
        self.assertEqual(EjecucionIA.objects.get().proveedor, 'ollama')

    def test_resultado_procesado_no_reemplaza_la_respuesta_original(self):
        self.configurar('gemini')
        respuesta = GestorIA().generar(pedido())
        seguimiento.registrar_resultado(respuesta, {'aceptadas': ['Salud pública']})
        ejecucion = EjecucionIA.objects.get()
        self.assertEqual(ejecucion.respuesta_original, '{"de": "gemini"}')
        self.assertEqual(ejecucion.resultado, {'aceptadas': ['Salud pública']})
        seguimiento.marcar_invalida(respuesta, 'sin_etiquetas_validas')
        ejecucion.refresh_from_db()
        self.assertEqual((ejecucion.estado, ejecucion.codigo_error), ('invalida', 'sin_etiquetas_validas'))
        self.assertEqual(ejecucion.respuesta_original, '{"de": "gemini"}')

    def test_un_fallo_al_guardar_el_historial_no_interrumpe_la_generacion(self):
        self.configurar('gemini')
        with patch.object(EjecucionIA.objects, 'create', side_effect=RuntimeError('base caída')), \
                self.assertLogs('core.services.ia.seguimiento', 'WARNING'):
            respuesta = GestorIA().generar(pedido())
        self.assertEqual(respuesta.texto, '{"de": "gemini"}')
        self.assertIsNone(respuesta.ejecucion_id)
        self.assertFalse(seguimiento.registrar_resultado(respuesta, {'x': 1}))
        self.assertEqual(EjecucionIA.objects.count(), 0)

    @override_settings(GEMINI_API_KEY=CLAVE_SECRETA)
    def test_no_guarda_claves_configuradas(self):
        self.configurar('gemini')
        self.gemini.client.models.generate_content.return_value = SimpleNamespace(text=f'eco {CLAVE_SECRETA}')
        GestorIA().generar(Solicitud(system=f'sistema {CLAVE_SECRETA}', contenido=f'texto {CLAVE_SECRETA}'))
        ejecucion = EjecucionIA.objects.get()
        for campo in (ejecucion.instrucciones, ejecucion.entrada, ejecucion.respuesta_original):
            self.assertNotIn(CLAVE_SECRETA, campo)
            self.assertIn(seguimiento.REDACTADO, campo)

    def test_entrada_extensa_se_recorta(self):
        texto = seguimiento.texto_seguro('a' * (seguimiento.LARGO_ENTRADA + 50), seguimiento.LARGO_ENTRADA)
        self.assertTrue(texto.startswith('a' * seguimiento.LARGO_ENTRADA))
        self.assertIn('recortado: 50', texto)

    def test_respuesta_que_no_es_del_contrato_queda_fallida(self):
        self.configurar('ollama', respaldo=False)
        with patch.object(self.ollama.proveedor, 'generar', return_value='texto suelto'), self.assertRaises(ErrorProveedor):
            GestorIA().generar(pedido())
        self.assertEqual(EjecucionIA.objects.get().codigo_error, 'respuesta_invalida')


class RegistroEnServiciosTests(BaseMotorIA):
    def test_analisis_de_publicacion_registra_resultado_guardado(self):
        self.configurar('gemini')
        pub = Publicacion.objects.create(hash_origen='seg-2', titulo='Hospital de Posadas', contenido='Texto')
        self.gemini.client.models.generate_content.return_value = SimpleNamespace(text=GEMINI_JSON)
        cliente = GeminiCliente.__new__(GeminiCliente)
        cliente.client, cliente.types, cliente.model_name, cliente.api_key = self.gemini.client, self.gemini.types, 'gemini-test', None
        with patch('core.services.gemini_cliente.time.sleep'):
            resultado = cliente.procesar_pendientes(batch_size=1)
        self.assertEqual(resultado['procesadas'], 1)
        ejecucion = EjecucionIA.objects.get()
        self.assertEqual((ejecucion.tarea, ejecucion.publicacion_id), ('analisis_publicacion', pub.pk))
        self.assertTrue(ejecucion.resultado['guardado'])
        self.assertEqual(ejecucion.resultado['polaridad'], 0.5)
        self.assertEqual(Sentimiento.objects.filter(id_publicacion_api=pub).count(), 1)

    def test_analisis_con_respuesta_invalida_queda_marcado(self):
        self.configurar('gemini')
        Publicacion.objects.create(hash_origen='seg-3', titulo='Otra', contenido='Texto')
        self.gemini.client.models.generate_content.return_value = SimpleNamespace(text='{"polaridad": 9}')
        cliente = GeminiCliente.__new__(GeminiCliente)
        cliente.client, cliente.types, cliente.model_name, cliente.api_key = self.gemini.client, self.gemini.types, 'gemini-test', None
        cliente.procesar_pendientes(batch_size=1)
        ejecucion = EjecucionIA.objects.get()
        self.assertEqual((ejecucion.estado, ejecucion.codigo_error), ('invalida', 'validacion_respuesta'))
        self.assertEqual(ejecucion.respuesta_original, '{"polaridad": 9}')

    def test_clasificacion_de_categorias_registra_el_lote(self):
        self.configurar('gemini')
        self.gemini.client.models.generate_content.return_value = SimpleNamespace(
            text=json.dumps([{'indice': 0, 'categoria': 'Salud'}]))
        resultado = clasificar_lote([{'titulo': 'Texto ambiguo', 'contenido': 'sin pistas', 'seccion': ''}])
        self.assertEqual(resultado[0]['metodo'], 'ia')
        ejecucion = EjecucionIA.objects.get()
        self.assertEqual((ejecucion.tarea, ejecucion.entidad), ('clasificacion_categorias', 'lote'))
        self.assertEqual(ejecucion.resultado['categorias'][0]['categoria'], 'Salud')


class SentimientoComentarioTests(TestCase):
    def setUp(self):
        self.pub = Publicacion.objects.create(hash_origen='seg-c', titulo='N', contenido='T')
        self.autor = User.objects.create_user('autor')
        self.comentario = Comentario.objects.create(publicacion=self.pub, autor=self.autor,
                                                    texto='Mi DNI es 12345678 y el servicio mejoró')

    def cliente(self, respuesta=None, error=False):
        def atender(request):
            if error:
                raise httpx.ConnectError('caido', request=request)
            return httpx.Response(200, json={'response': respuesta})
        return httpx.Client(transport=httpx.MockTransport(atender))

    def test_registra_sin_copiar_el_texto_del_comentario(self):
        sentimiento_comentarios.analizar_comentario(
            self.comentario, usar_ia=True,
            cliente_http=self.cliente('{"polaridad": 0.6, "confianza": 0.9, "categoria": "Salud"}'))
        ejecucion = EjecucionIA.objects.get()
        self.assertEqual((ejecucion.tarea, ejecucion.proveedor, ejecucion.estado), ('sentimiento_comentario', 'ollama', 'exitosa'))
        self.assertEqual((ejecucion.entidad, ejecucion.entidad_id), ('comentario', self.comentario.pk))
        self.assertEqual(ejecucion.entrada, '')
        self.assertNotIn('12345678', ejecucion.respuesta_original + json.dumps(ejecucion.resultado))
        self.assertEqual(ejecucion.resultado['polaridad'], 0.6)

    def test_ollama_caido_y_respuesta_invalida(self):
        sentimiento_comentarios.analizar_comentario(self.comentario, usar_ia=True, cliente_http=self.cliente(error=True))
        sentimiento_comentarios.analizar_comentario(self.comentario, usar_ia=True, forzar=True,
                                                    cliente_http=self.cliente('no es json'))
        fallida, invalida = EjecucionIA.objects.order_by('pk')
        self.assertEqual((fallida.estado, fallida.codigo_error), ('fallida', 'ollama_sin_respuesta'))
        self.assertEqual((invalida.estado, invalida.respuesta_original), ('invalida', 'no es json'))


class PanelSeguimientoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('configurar_roles', stdout=StringIO())
        cls.admin = User.objects.create_user('admin-ia', is_staff=True)
        cls.admin.groups.add(Group.objects.get(name='Administrador'))
        cls.lector = User.objects.create_user('lector-ia')
        cls.lector.groups.add(Group.objects.get(name='Usuario'))
        cls.pub = Publicacion.objects.create(hash_origen='panel', titulo='Noticia del panel', contenido='Texto')
        crear = EjecucionIA.objects.create
        cls.exitosa = crear(tarea='etiquetado_tematico', proveedor='gemini', modelo='gemini-2.5', estado='exitosa',
                            publicacion=cls.pub, entidad='publicacion', entidad_id=cls.pub.pk,
                            entrada='ENTRADA-VISIBLE', respuesta_original='{"etiquetas": ["Salud pública"]}',
                            resultado={'aceptadas': [{'slug': 'salud-publica', 'nombre': 'Salud pública'}]})
        cls.fallida = crear(tarea='analisis_publicacion', proveedor='ollama', modelo='llama3.1:latest',
                            estado='fallida', codigo_error='timeout', fecha=timezone.now() - timedelta(days=10))
        cls.invalida = crear(tarea='revision_departamentos', proveedor='gemini', modelo='gemini-2.5',
                             estado='invalida', codigo_error='validacion_respuesta', entidad='lote', referencias=[cls.pub.pk])
        cls.url = reverse('seguimiento_ia')

    def test_acceso_restringido_a_administradores(self):
        detalle = reverse('detalle_ejecucion_ia', args=[self.exitosa.identificador])
        for usuario, esperado in ((None, 302), (self.lector, 403)):
            self.client.logout()
            if usuario:
                self.client.force_login(usuario)
            for url in (self.url, detalle):
                with self.subTest(usuario=usuario, url=url):
                    respuesta = self.client.get(url)
                    self.assertEqual(respuesta.status_code, esperado)
                    self.assertNotIn(b'ENTRADA-VISIBLE', respuesta.content)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_la_navegacion_publica_no_muestra_el_panel(self):
        self.client.force_login(self.lector)
        self.assertNotContains(self.client.get(reverse('landing'), follow=True), self.url)

    def test_filtros_por_tipo_proveedor_estado_modelo_y_fecha(self):
        self.client.force_login(self.admin)
        casos = [
            ({'tarea': 'etiquetado_tematico'}, {self.exitosa}),
            ({'proveedor': 'ollama'}, {self.fallida}),
            ({'estado': 'invalida'}, {self.invalida}),
            ({'modelo': 'gemini-2.5'}, {self.exitosa, self.invalida}),
            ({'hasta': (timezone.localdate() - timedelta(days=5)).isoformat()}, {self.fallida}),
            ({'publicacion': self.pub.pk}, {self.exitosa, self.invalida}),
        ]
        for filtros, esperadas in casos:
            with self.subTest(filtros=filtros):
                respuesta = self.client.get(self.url, filtros)
                self.assertEqual(respuesta.status_code, 200)
                self.assertEqual(set(respuesta.context['pagina'].object_list), esperadas)

    def test_fechas_invertidas_se_rechazan(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(self.url, {'desde': '2026-11-07', 'hasta': '2026-11-01'})
        self.assertEqual(respuesta.status_code, 400)

    def test_detalle_muestra_entrada_respuesta_y_resultado(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('detalle_ejecucion_ia', args=[self.exitosa.identificador]))
        self.assertContains(respuesta, 'ENTRADA-VISIBLE')
        self.assertContains(respuesta, 'Respuesta original del modelo')
        self.assertContains(respuesta, 'Resultado procesado que usa el sistema')
        self.assertContains(respuesta, 'salud-publica')
        self.assertContains(respuesta, 'Noticia del panel')
        fallida = self.client.get(reverse('detalle_ejecucion_ia', args=[self.fallida.identificador]))
        self.assertContains(fallida, 'timeout')

    def test_historial_sobrevive_a_la_publicacion(self):
        pk = self.pub.pk
        Publicacion.objects.filter(pk=pk).delete()
        self.assertEqual(EjecucionIA.objects.filter(publicacion_id=pk).count(), 1)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(self.url), f'Noticia #{pk} (eliminada)')
