"""Proveedor Ollama (modelo local, por defecto llama3.1:latest).

Sólo usa la API HTTP local de Ollama: no descarga modelos (nunca llama a
`/api/pull`), no depende de servicios externos y no registra el contenido de
los pedidos. La dirección es configurable porque dentro de Docker `localhost`
es el propio contenedor: con Docker Desktop el equipo anfitrión se alcanza en
`http://host.docker.internal:11434` (ver docker-compose.yml y README).

Variables de entorno (leídas en cada llamada):
- OLLAMA_BASE_URL: dirección del servicio (por defecto http://127.0.0.1:11434).
- OLLAMA_MODELO_CHAT: modelo a usar (por defecto llama3.1:latest).
- OLLAMA_TIMEOUT: segundos máximos de espera de la respuesta.
- OLLAMA_NUM_CTX: ventana de contexto pedida (por defecto 8192).
- OLLAMA_KEEP_ALIVE: cuánto mantiene el modelo cargado (por defecto 5m).
"""
import json
import os
from urllib.parse import urlsplit

try:
    import httpx  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - httpx llega como dependencia de google-genai
    httpx = None

from .base import (
    ESTADO_CONECTADO, ESTADO_DESCONECTADO, ESTADO_ERROR_CONEXION,
    PROVEEDOR_OLLAMA, ErrorProveedor, EstadoProveedor, ProveedorIA, RespuestaIA,
)

BASE_POR_DEFECTO = 'http://127.0.0.1:11434'
MODELO_POR_DEFECTO = 'llama3.1:latest'
TIMEOUT_POR_DEFECTO = 60.0
TIMEOUT_CONEXION = 5.0
TIMEOUT_PRUEBA = 5.0
NUM_CTX_POR_DEFECTO = 8192
KEEP_ALIVE_POR_DEFECTO = '5m'
# Llama tiende a devolver un objeto aunque se le pida una lista: se le aclara el formato.
_AVISO_LISTA = ('\n\nFORMATO: respondé siempre con un arreglo JSON de objetos, aunque haya un solo '
                'elemento, sin envolverlo en otro objeto ni agregar claves adicionales.')


def config_ollama(timeout_por_defecto=TIMEOUT_POR_DEFECTO):
    """(base, modelo, timeout) desde el entorno; fuente única para todo el proyecto."""
    base = (os.environ.get('OLLAMA_BASE_URL') or BASE_POR_DEFECTO).strip().rstrip('/')
    modelo = (os.environ.get('OLLAMA_MODELO_CHAT') or MODELO_POR_DEFECTO).strip()
    try:
        timeout = float(os.environ.get('OLLAMA_TIMEOUT', timeout_por_defecto))
        if not 0 < timeout <= 600:
            raise ValueError
    except (TypeError, ValueError):
        timeout = timeout_por_defecto
    return base, modelo, timeout


def _entero_entorno(nombre, por_defecto):
    try:
        valor = int(os.environ.get(nombre, por_defecto))
        return valor if valor > 0 else por_defecto
    except (TypeError, ValueError):
        return por_defecto


def _base_valida(base):
    partes = urlsplit(base)
    return partes.scheme in ('http', 'https') and bool(partes.hostname)


def _nombres_equivalentes(modelo, instalado):
    return instalado == modelo or (':' not in modelo and instalado == f'{modelo}:latest')


class ProveedorOllama(ProveedorIA):
    nombre = PROVEEDOR_OLLAMA
    etiqueta = 'Llama 3.1'

    def __init__(self, cliente_http=None):
        # `cliente_http` permite inyectar un httpx.Client (pruebas); no se cierra aquí.
        self._cliente_http = cliente_http

    @property
    def modelo(self):
        return config_ollama()[1]

    def configurado(self):
        return httpx is not None and _base_valida(config_ollama()[0])

    def _con_cliente(self, timeout, operacion):
        if httpx is None:
            raise ErrorProveedor('httpx_no_disponible', temporal=False)
        if self._cliente_http is not None:
            return operacion(self._cliente_http)
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=min(TIMEOUT_CONEXION, timeout))) as http:
            return operacion(http)

    def _llamar(self, metodo, ruta, timeout, **kwargs):
        """Una única petición HTTP; traduce los fallos a ErrorProveedor clasificado."""
        base = config_ollama()[0]
        if not _base_valida(base):
            raise ErrorProveedor('configuracion_invalida', temporal=False)
        try:
            response = self._con_cliente(
                timeout, lambda http: getattr(http, metodo)(f'{base}{ruta}', timeout=timeout, **kwargs))
        except httpx.TimeoutException as exc:
            raise ErrorProveedor('timeout', temporal=True) from exc
        except httpx.InvalidURL as exc:
            raise ErrorProveedor('configuracion_invalida', temporal=False) from exc
        except httpx.HTTPError as exc:
            # Conexión rechazada, DNS, reset, protocolo: el servicio no está disponible.
            raise ErrorProveedor('sin_conexion', temporal=True) from exc
        if response.status_code >= 500 or response.status_code == 429:
            raise ErrorProveedor('no_disponible', temporal=True)
        if response.status_code == 404:
            raise ErrorProveedor('modelo_inexistente', temporal=False)
        if response.status_code >= 400:
            raise ErrorProveedor('solicitud_rechazada', temporal=False)
        return response

    def generar(self, solicitud):
        base, modelo, timeout = config_ollama()
        sistema = solicitud.system
        if solicitud.esperado == 'lista':
            sistema += _AVISO_LISTA
        carga = {
            'model': modelo,
            'stream': False,
            'format': 'json',
            'messages': [
                {'role': 'system', 'content': sistema},
                {'role': 'user', 'content': solicitud.contenido},
            ],
            'options': {
                'temperature': solicitud.temperatura,
                'num_ctx': _entero_entorno('OLLAMA_NUM_CTX', NUM_CTX_POR_DEFECTO),
            },
            'keep_alive': os.environ.get('OLLAMA_KEEP_ALIVE') or KEEP_ALIVE_POR_DEFECTO,
        }
        response = self._llamar('post', '/api/chat', timeout, json=carga)
        try:
            envoltorio = response.json()
        except (ValueError, RecursionError) as exc:
            raise ErrorProveedor('respuesta_invalida', temporal=False) from exc
        mensaje = envoltorio.get('message') if isinstance(envoltorio, dict) else None
        texto = mensaje.get('content') if isinstance(mensaje, dict) else None
        if not isinstance(texto, str) or not texto.strip():
            raise ErrorProveedor('respuesta_invalida', temporal=False)
        if solicitud.esperado == 'lista':
            texto = _normalizar_lista(texto)
        return RespuestaIA(texto=texto, proveedor=self.nombre, modelo=modelo)

    def es_temporal(self, exc):
        return isinstance(exc, ErrorProveedor) and exc.temporal

    def probar_conexion(self):
        base, modelo, _ = config_ollama()
        if not self.configurado():
            return EstadoProveedor(self.nombre, ESTADO_ERROR_CONEXION,
                                   'La dirección de Ollama configurada no es válida.', modelo)
        try:
            response = self._llamar('get', '/api/tags', TIMEOUT_PRUEBA)
            datos = response.json()
        except ErrorProveedor as exc:
            if exc.temporal:
                return EstadoProveedor(self.nombre, ESTADO_DESCONECTADO,
                                       'Ollama no responde. Verificá que esté instalado y en ejecución.', modelo)
            return EstadoProveedor(self.nombre, ESTADO_ERROR_CONEXION,
                                   'Ollama respondió con un error.', modelo)
        except (ValueError, RecursionError):
            return EstadoProveedor(self.nombre, ESTADO_ERROR_CONEXION,
                                   'Ollama devolvió una respuesta inesperada.', modelo)
        modelos = datos.get('models') if isinstance(datos, dict) else None
        nombres = [m.get('name') for m in modelos if isinstance(m, dict)] if isinstance(modelos, list) else []
        if not any(isinstance(n, str) and _nombres_equivalentes(modelo, n) for n in nombres):
            # Nunca se descarga automáticamente: sólo se informa.
            return EstadoProveedor(
                self.nombre, ESTADO_ERROR_CONEXION,
                f'Ollama responde, pero el modelo {modelo} no está instalado en el equipo.', modelo)
        return EstadoProveedor(self.nombre, ESTADO_CONECTADO, 'Ollama responde y el modelo está instalado (esto no garantiza que pueda generar).', modelo)


def _normalizar_lista(texto):
    """Adapta la salida de Llama a la lista JSON que valida el servicio.

    Con `format: json` el modelo tiende a responder un objeto: o bien envuelve la
    lista ({"resultados": [...]}) o devuelve un único elemento suelto. Sólo se
    corrigen esas dos formas; cualquier otra queda intacta y la rechaza el
    validador del servicio (que sigue siendo estricto).
    """
    try:
        dato = json.loads(texto)
    except (ValueError, RecursionError):
        return texto
    if not isinstance(dato, dict):
        return texto
    listas = [valor for valor in dato.values() if isinstance(valor, list)]
    if len(dato) == 1 and listas:
        return json.dumps(listas[0], ensure_ascii=False)
    if dato and not listas:
        return json.dumps([dato], ensure_ascii=False)
    return texto
