"""Contrato común de los proveedores de IA de TrendWatch.

Los servicios de negocio (análisis de publicaciones, clasificación de categorías,
revisión de departamentos) piden el procesamiento al gestor central
(`core.services.ia.gestor`) y no conocen qué proveedor lo ejecuta. Cada
proveedor traduce el pedido a su API y devuelve siempre el mismo objeto
(`RespuestaIA`) con el texto JSON generado: la validación y la persistencia
siguen siendo responsabilidad de cada servicio.
"""
from dataclasses import dataclass

PROVEEDOR_GEMINI = 'gemini'
PROVEEDOR_OLLAMA = 'ollama'
PROVEEDORES = (PROVEEDOR_GEMINI, PROVEEDOR_OLLAMA)

ESTADO_CONECTADO = 'conectado'
ESTADO_DESCONECTADO = 'desconectado'
ESTADO_ERROR_CONEXION = 'error_conexion'
ESTADO_NO_CONFIGURADO = 'no_configurado'
ETIQUETAS_ESTADO = {
    ESTADO_CONECTADO: 'Conectado',
    ESTADO_DESCONECTADO: 'Desconectado',
    ESTADO_ERROR_CONEXION: 'Error de conexión',
    ESTADO_NO_CONFIGURADO: 'No configurado',
}


@dataclass(frozen=True)
class Solicitud:
    """Pedido de generación independiente del proveedor.

    `esperado` indica la forma del JSON que valida el servicio que llama
    ('objeto' o 'lista'); `tarea` y `referencia` sólo sirven para el registro
    (nunca debe ir contenido de noticias en `referencia`, sólo un id).
    """
    system: str
    contenido: str
    temperatura: float = 0.1
    esperado: str = 'objeto'
    tarea: str = 'generico'
    referencia: object = None
    # Seguimiento (core.services.ia.seguimiento): a qué se refiere el pedido.
    # `entidad='publicacion'` vincula el registro con `referencia` como id de publicación;
    # `referencias` lista los ids de un lote. `registrar_entrada=False` evita copiar
    # al historial textos que pueden contener datos personales.
    entidad: str = ''
    referencias: tuple = ()
    registrar_entrada: bool = True


@dataclass(frozen=True)
class RespuestaIA:
    texto: object
    proveedor: str
    modelo: str
    # True si respondió el motor alternativo porque el principal falló.
    respaldo: bool = False
    # Registro de seguimiento de esta respuesta (None si no pudo guardarse).
    ejecucion_id: object = None

    @property
    def text(self):
        """Compatibilidad con el objeto de respuesta del SDK de Gemini."""
        return self.texto


@dataclass(frozen=True)
class EstadoProveedor:
    proveedor: str
    estado: str
    detalle: str
    modelo: str

    @property
    def etiqueta(self):
        return ETIQUETAS_ESTADO[self.estado]


class ErrorProveedor(RuntimeError):
    """Fallo propio de un proveedor, ya clasificado.

    `codigo` es un identificador corto y seguro para registros (nunca el
    mensaje del proveedor); `temporal` habilita el cambio al motor alternativo.
    """

    def __init__(self, codigo, temporal=False):
        super().__init__(codigo)
        self.codigo = codigo
        self.temporal = temporal


PROMPT_PRUEBA_GENERACION = 'Respondé únicamente con el objeto JSON {"ok": true}.'


class ProveedorIA:
    nombre = ''
    etiqueta = ''
    # ¿Sus resultados pueden guardarse como análisis de publicaciones (sentimiento y
    # localidades con coordenadas)? Sólo si su calidad se validó como equivalente a Gemini.
    # Es una capacidad del proveedor, independiente de si actúa como principal o respaldo.
    persiste_analisis_publicaciones = False

    @property
    def modelo(self):
        raise NotImplementedError

    def configurado(self):
        raise NotImplementedError

    def generar(self, solicitud):
        raise NotImplementedError

    def es_temporal(self, exc):
        """True si `exc` es un fallo de disponibilidad (red, timeout, 5xx, límite corto)."""
        raise NotImplementedError

    def codigo_error(self, exc):
        """Código breve y seguro del error, apto para el registro."""
        return getattr(exc, 'codigo', None) or type(exc).__name__

    def probar_conexion(self):
        """Comprueba el proveedor sin ejecutar un análisis real."""
        raise NotImplementedError

    def probar_generacion(self):
        """Comprueba que el motor *genera* una respuesta (pedido mínimo fijo, sin datos de noticias).

        Distinto de `probar_conexion`: un servicio puede responder por metadatos y aun así
        fallar al generar (sobrecarga, timeouts, modelo sin memoria). Consume una llamada
        mínima; nada se guarda y no hay respaldo (se prueba este motor y sólo este).
        """
        if not self.configurado():
            return EstadoProveedor(self.nombre, ESTADO_NO_CONFIGURADO,
                                   'No está configurado en el servidor.', self.modelo)
        try:
            respuesta = self.generar(Solicitud(system=PROMPT_PRUEBA_GENERACION, contenido='ping',
                                               temperatura=0.0, tarea='prueba_generacion'))
        except Exception as exc:  # noqa: BLE001 - se clasifica sin exponer el mensaje.
            codigo = self.codigo_error(exc)
            if self.es_temporal(exc):
                return EstadoProveedor(
                    self.nombre, ESTADO_DESCONECTADO,
                    f'No pudo generar: el servicio no respondió, está sobrecargado o superó el tiempo de espera ({codigo}).',
                    self.modelo)
            return EstadoProveedor(self.nombre, ESTADO_ERROR_CONEXION,
                                   f'No pudo generar: el servicio rechazó el pedido ({codigo}).', self.modelo)
        if not isinstance(respuesta.texto, str) or not respuesta.texto.strip():
            return EstadoProveedor(self.nombre, ESTADO_ERROR_CONEXION,
                                   'No pudo generar: devolvió una respuesta vacía.', self.modelo)
        return EstadoProveedor(self.nombre, ESTADO_CONECTADO,
                               'Generó una respuesta de prueba correctamente.', self.modelo)
