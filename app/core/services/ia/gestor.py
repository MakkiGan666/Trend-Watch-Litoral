"""Gestor central de proveedores de IA: selección del motor y respaldo automático.

Reglas:
- El motor principal y el respaldo automático salen de `ConfiguracionIA`
  (administrable desde el panel). Sin fila, o con la tabla aún sin migrar,
  rige el valor seguro por defecto: Gemini con respaldo activado.
- El respaldo sólo se usa ante fallos de disponibilidad del principal (conexión,
  timeout, 5xx, límite corto de frecuencia). Errores de validación, permisos,
  configuración o solicitud incorrecta se informan sin cambiar de proveedor.
- Cada pedido hace como máximo un intento por proveedor (sin bucles). La
  generación no escribe en la base: el servicio que llama persiste el resultado
  después, así un cambio de motor nunca repite una operación con efectos.
- El registro dice qué proveedor respondió y cuándo hubo un cambio de motor, sin
  claves ni contenido de noticias.
"""
import logging
from dataclasses import dataclass

from django.db import DatabaseError, transaction
from django.utils import timezone

from core.models import ConfiguracionIA, EjecucionIA

from . import seguimiento
from .base import PROVEEDOR_GEMINI, PROVEEDOR_OLLAMA, ErrorProveedor, RespuestaIA
from .gemini import ProveedorGemini
from .ollama import ProveedorOllama

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConfigEfectiva:
    principal: str
    respaldo_automatico: bool

    @property
    def alternativo(self):
        return PROVEEDOR_OLLAMA if self.principal == PROVEEDOR_GEMINI else PROVEEDOR_GEMINI


def configuracion_actual():
    """Configuración vigente; ante cualquier problema de lectura usa el valor seguro."""
    try:
        with transaction.atomic():  # punto de guardado: un fallo no aborta una transacción abierta
            fila = ConfiguracionIA.objects.filter(pk=ConfiguracionIA.PK).first()
    except DatabaseError:
        logger.warning('IA: no se pudo leer la configuración; se usa la predeterminada.')
        fila = None
    if fila is None or fila.motor_principal not in (PROVEEDOR_GEMINI, PROVEEDOR_OLLAMA):
        return ConfigEfectiva(ConfiguracionIA.PRINCIPAL_POR_DEFECTO, ConfiguracionIA.RESPALDO_POR_DEFECTO)
    return ConfigEfectiva(fila.motor_principal, bool(fila.respaldo_automatico))


def _registrar_cambio(origen, destino, codigo):
    """Guarda el último cambio de motor para mostrarlo en el panel; nunca falla al llamador."""
    try:
        with transaction.atomic():
            ConfiguracionIA.objects.update_or_create(
                pk=ConfiguracionIA.PK,
                defaults={
                    'ultimo_respaldo_en': timezone.now(),
                    'ultimo_respaldo_detalle': f'{origen} → {destino} ({codigo})'[:120],
                },
            )
    except Exception:  # noqa: BLE001 - es información auxiliar; el pedido no debe fallar por esto.
        logger.warning('IA: no se pudo guardar el último cambio de motor.')


class GestorIA:
    def __init__(self, cliente_gemini=None, reintentos_gemini=False, ollama=None):
        self._proveedores = {
            PROVEEDOR_GEMINI: ProveedorGemini(cliente=cliente_gemini, con_reintentos=reintentos_gemini),
            PROVEEDOR_OLLAMA: ollama or ProveedorOllama(),
        }

    def proveedor(self, nombre):
        return self._proveedores[nombre]

    def persiste_analisis_publicaciones(self, nombre):
        """True si los resultados del proveedor `nombre` pueden guardarse como análisis de publicaciones."""
        proveedor = self._proveedores.get(nombre)
        return bool(proveedor and proveedor.persiste_analisis_publicaciones)

    def principal(self):
        return self._proveedores[configuracion_actual().principal]

    def disponible(self):
        """True si el motor principal está configurado para recibir pedidos."""
        return self.principal().configurado()

    def generar(self, solicitud):
        config = configuracion_actual()
        principal = self._proveedores[config.principal]
        try:
            return self._intentar(principal, solicitud, respaldo=False)
        except Exception as exc:  # noqa: BLE001 - se clasifica antes de decidir.
            temporal = principal.es_temporal(exc)
            codigo = principal.codigo_error(exc)
            motivo = None
            if not config.respaldo_automatico:
                motivo = 'respaldo_desactivado'
            elif not temporal:
                motivo = 'error_no_temporal'
            alternativo = self._proveedores[config.alternativo]
            if motivo is None and not alternativo.configurado():
                motivo = 'respaldo_no_configurado'
            if motivo is not None:
                logger.warning('IA: tarea=%s proveedor=%s fallo=%s sin_cambio_de_motor=%s',
                               solicitud.tarea, principal.nombre, codigo, motivo)
                raise
            logger.warning('IA: cambio de motor tarea=%s de=%s a=%s motivo=%s referencia=%s',
                           solicitud.tarea, principal.nombre, alternativo.nombre, codigo, solicitud.referencia)
            _registrar_cambio(principal.nombre, alternativo.nombre, codigo)
            try:
                return self._intentar(alternativo, solicitud, respaldo=True)
            except Exception as exc_alt:
                logger.error('IA: tarea=%s ambos motores fallaron principal=%s(%s) respaldo=%s(%s)',
                             solicitud.tarea, principal.nombre, codigo,
                             alternativo.nombre, alternativo.codigo_error(exc_alt))
                raise exc_alt from exc

    def _intentar(self, proveedor, solicitud, respaldo):
        cronometro = seguimiento.Cronometro()
        try:
            respuesta = proveedor.generar(solicitud)
            if not isinstance(respuesta, RespuestaIA):
                raise ErrorProveedor('respuesta_invalida', temporal=False)
        except Exception as exc:
            # Sólo el código clasificado: el mensaje del proveedor puede incluir datos del pedido.
            _registrar_intento(solicitud, proveedor.nombre, proveedor.modelo, respaldo, cronometro,
                               estado=EjecucionIA.Estado.FALLIDA, codigo_error=proveedor.codigo_error(exc),
                               detalle_error=type(exc).__name__)
            raise
        ejecucion_id = _registrar_intento(solicitud, respuesta.proveedor, respuesta.modelo, respaldo, cronometro,
                                          estado=EjecucionIA.Estado.EXITOSA, respuesta=respuesta.texto)
        respuesta = RespuestaIA(respuesta.texto, respuesta.proveedor, respuesta.modelo,
                                respaldo=bool(respaldo or respuesta.respaldo), ejecucion_id=ejecucion_id)
        logger.info('IA: tarea=%s proveedor=%s modelo=%s respaldo=%s referencia=%s',
                    solicitud.tarea, respuesta.proveedor, respuesta.modelo,
                    'si' if respaldo else 'no', solicitud.referencia)
        return respuesta


def _registrar_intento(solicitud, proveedor, modelo, respaldo, cronometro, **campos):
    """Un registro de seguimiento por intento de proveedor (incluido el respaldo)."""
    return seguimiento.registrar(
        tarea=solicitud.tarea, proveedor=proveedor, modelo=modelo, respaldo=respaldo,
        instrucciones=solicitud.system if solicitud.registrar_entrada else '',
        entrada=solicitud.contenido if solicitud.registrar_entrada else '',
        duracion_ms=cronometro.ms, entidad=solicitud.entidad,
        entidad_id=solicitud.referencia if solicitud.entidad else None,
        referencias=solicitud.referencias, **campos,
    )


def obtener_gestor(cliente_gemini=None, reintentos_gemini=False):
    """Gestor listo para usar; `cliente_gemini` permite que un GeminiCliente propio sea el proveedor."""
    return GestorIA(cliente_gemini=cliente_gemini, reintentos_gemini=reintentos_gemini)
