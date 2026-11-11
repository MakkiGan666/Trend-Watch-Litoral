"""Proveedor Gemini (API de Google).

Envuelve el cliente existente (`core.services.gemini_cliente.gemini_cliente`)
sin duplicar su configuración: misma clave, mismo modelo y misma clasificación
de errores. El cliente se resuelve en cada llamada para respetar el estado real
del proceso (y los reemplazos que hacen las pruebas).
"""
from .base import (
    ESTADO_CONECTADO, ESTADO_DESCONECTADO, ESTADO_ERROR_CONEXION, ESTADO_NO_CONFIGURADO,
    PROVEEDOR_GEMINI, ErrorProveedor, EstadoProveedor, ProveedorIA, RespuestaIA,
)

# Detalle mostrable por tipo de error; nunca se muestra el mensaje del proveedor.
_DETALLE_POR_TIPO = {
    'autenticacion': 'Google rechazó las credenciales configuradas.',
    'modelo_inexistente': 'El modelo configurado no existe para esta cuenta.',
    'cuota_agotada': 'Se agotó la cuota de uso de la API.',
    'limite_frecuencia': 'La API alcanzó su límite de frecuencia.',
    'limite_no_determinado': 'La API alcanzó su límite de uso.',
}


class ProveedorGemini(ProveedorIA):
    nombre = PROVEEDOR_GEMINI
    etiqueta = 'Gemini'
    persiste_analisis_publicaciones = True

    def __init__(self, cliente=None, con_reintentos=False):
        self._cliente = cliente
        # El análisis de publicaciones conserva sus reintentos y su registro propios.
        self._con_reintentos = con_reintentos

    @property
    def cliente(self):
        if self._cliente is not None:
            return self._cliente
        # Importación diferida: gemini_cliente importa el scraper, que importa la clasificación.
        from core.services import gemini_cliente as modulo
        return modulo.gemini_cliente

    @property
    def modelo(self):
        return getattr(self.cliente, 'model_name', '') or ''

    def configurado(self):
        cliente = self.cliente
        return getattr(cliente, 'client', None) is not None and getattr(cliente, 'types', None) is not None

    def generar(self, solicitud):
        cliente = self.cliente
        if not self.configurado():
            raise ErrorProveedor('no_configurado', temporal=False)
        if self._con_reintentos:
            respuesta = cliente._generar_con_reintentos(solicitud.referencia, solicitud.contenido)
        else:
            respuesta = cliente.client.models.generate_content(
                model=cliente.model_name,
                contents=solicitud.contenido,
                config=cliente.types.GenerateContentConfig(
                    system_instruction=solicitud.system,
                    response_mime_type='application/json',
                    temperature=solicitud.temperatura,
                ),
            )
        return RespuestaIA(texto=getattr(respuesta, 'text', None), proveedor=self.nombre, modelo=self.modelo)

    def es_temporal(self, exc):
        if isinstance(exc, ErrorProveedor):
            return exc.temporal
        from core.services.gemini_cliente import clasificar_error_gemini
        return bool(clasificar_error_gemini(exc)[2])

    def codigo_error(self, exc):
        if isinstance(exc, ErrorProveedor):
            return exc.codigo
        from core.services.gemini_cliente import clasificar_error_gemini
        return clasificar_error_gemini(exc)[0]

    def probar_conexion(self):
        if not self.configurado():
            return EstadoProveedor(
                self.nombre, ESTADO_NO_CONFIGURADO,
                'Falta configurar GEMINI_API_KEY en el entorno del servidor.', self.modelo)
        try:
            # Consulta de metadatos del modelo: no genera texto ni consume cuota de análisis.
            self.cliente.client.models.get(model=self.cliente.model_name)
        except Exception as exc:  # noqa: BLE001 - se clasifica sin exponer el mensaje.
            from core.services.gemini_cliente import clasificar_error_gemini
            tipo, codigo, _, _ = clasificar_error_gemini(exc)
            if tipo in ('red', 'no_disponible'):
                return EstadoProveedor(self.nombre, ESTADO_DESCONECTADO,
                                       'La API de Google no respondió.', self.modelo)
            detalle = _DETALLE_POR_TIPO.get(tipo) or (
                f'Google devolvió un error (HTTP {codigo}).' if codigo else 'No se pudo consultar la API de Google.')
            return EstadoProveedor(self.nombre, ESTADO_ERROR_CONEXION, detalle, self.modelo)
        return EstadoProveedor(self.nombre, ESTADO_CONECTADO, 'La API responde (esto no garantiza que pueda generar).', self.modelo)
