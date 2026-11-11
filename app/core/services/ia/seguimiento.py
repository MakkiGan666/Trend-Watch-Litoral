"""Seguimiento centralizado de las ejecuciones de IA (historial y trazabilidad).

Toda llamada a un modelo pasa por aquí una sola vez:
- `GestorIA` registra automáticamente cada intento de proveedor (Gemini u Ollama),
  con la entrada, la respuesta original, el tiempo y el estado de la llamada.
- El servicio que valida la respuesta completa el mismo registro con
  `registrar_resultado` (resultado normalizado que usa el sistema) o
  `marcar_invalida` (la respuesta no superó la validación).
- Las llamadas que no usan el gestor (sentimiento de comentarios con Ollama)
  usan `registrar` directamente.

Garantías:
- Nunca interrumpe la funcionalidad principal: cualquier error al guardar se
  registra en el log y se ignora (devuelve None). Cada escritura va en su propio
  punto de guardado para no abortar una transacción abierta del llamador.
- No guarda credenciales: además de no incluirlas en los pedidos, se borra del
  texto cualquier aparición de las claves configuradas.
- Historial inmutable: la respuesta original nunca se modifica después de
  registrarse; sólo se completan el resultado y el estado.
"""
import json
import logging
import os
import time

from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)

LARGO_INSTRUCCIONES = 8000
LARGO_ENTRADA = 20000
LARGO_RESPUESTA = 50000
LARGO_DETALLE = 240
_CLAVES_SENSIBLES = ('GEMINI_API_KEY', 'GOOGLE_API_KEY')
REDACTADO = '[dato sensible omitido]'


def _secretos():
    valores = set()
    for nombre in _CLAVES_SENSIBLES:
        for valor in (os.environ.get(nombre), getattr(settings, nombre, None)):
            if isinstance(valor, str) and len(valor.strip()) >= 8:
                valores.add(valor.strip())
    return valores


def texto_seguro(valor, limite):
    """Texto apto para el historial: sin claves configuradas y con un largo máximo."""
    if valor is None:
        return ''
    if not isinstance(valor, str):
        try:
            valor = json.dumps(valor, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            valor = str(valor)
    for secreto in _secretos():
        valor = valor.replace(secreto, REDACTADO)
    if len(valor) > limite:
        valor = valor[:limite] + f'\n[… recortado: {len(valor) - limite} caracteres más]'
    return valor


def _json_seguro(valor):
    """Resultado serializable y sin claves (los JSONField no aceptan objetos arbitrarios)."""
    if valor is None:
        return None
    try:
        texto = json.dumps(valor, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return {'valor': texto_seguro(str(valor), LARGO_RESPUESTA)}
    for secreto in _secretos():
        texto = texto.replace(secreto, REDACTADO)
    return json.loads(texto)


def _entero_o_none(valor):
    return valor if isinstance(valor, int) and not isinstance(valor, bool) and valor >= 0 else None


def registrar(*, tarea, proveedor, modelo='', estado, instrucciones='', entrada='', respuesta=None,
              resultado=None, codigo_error='', detalle_error='', duracion_ms=None, respaldo=False,
              entidad='', entidad_id=None, referencias=()):
    """Crea un registro de ejecución. Devuelve su id, o None si no pudo guardarse."""
    from core.models import EjecucionIA
    entidad_id = _entero_o_none(entidad_id)
    try:
        with transaction.atomic():
            ejecucion = EjecucionIA.objects.create(
                tarea=(tarea or EjecucionIA.Tarea.OTRA)[:40],
                proveedor=(proveedor or '')[:16],
                modelo=(modelo or '')[:80],
                respaldo=bool(respaldo),
                publicacion_id=entidad_id if entidad == 'publicacion' else None,
                entidad=(entidad or '')[:20],
                entidad_id=entidad_id,
                referencias=[r for r in (_entero_o_none(r) for r in referencias or ()) if r is not None][:200],
                instrucciones=texto_seguro(instrucciones, LARGO_INSTRUCCIONES),
                entrada=texto_seguro(entrada, LARGO_ENTRADA),
                respuesta_original=texto_seguro(respuesta, LARGO_RESPUESTA),
                resultado=_json_seguro(resultado),
                estado=estado,
                codigo_error=(codigo_error or '')[:64],
                detalle_error=texto_seguro(detalle_error, LARGO_DETALLE)[:LARGO_DETALLE],
                duracion_ms=_entero_o_none(duracion_ms),
            )
        return ejecucion.pk
    except Exception:  # noqa: BLE001 - el historial nunca rompe la operación principal.
        logger.warning('IA: no se pudo registrar el seguimiento de la tarea=%s.', tarea, exc_info=True)
        return None


def _actualizar(ejecucion_id, campos):
    from core.models import EjecucionIA
    if not ejecucion_id:
        return False
    try:
        with transaction.atomic():
            return bool(EjecucionIA.objects.filter(pk=ejecucion_id).update(**campos))
    except Exception:  # noqa: BLE001
        logger.warning('IA: no se pudo completar el seguimiento ejecucion=%s.', ejecucion_id, exc_info=True)
        return False


def _id_de(respuesta_o_id):
    if isinstance(respuesta_o_id, int) and not isinstance(respuesta_o_id, bool):
        return respuesta_o_id
    return getattr(respuesta_o_id, 'ejecucion_id', None)


def registrar_resultado(respuesta_o_id, resultado):
    """Guarda el resultado normalizado que el sistema usó a partir de la respuesta."""
    return _actualizar(_id_de(respuesta_o_id), {'resultado': _json_seguro(resultado)})


def marcar_invalida(respuesta_o_id, codigo, detalle='', resultado=None):
    """La respuesta llegó pero no superó la validación del servicio."""
    from core.models import EjecucionIA
    campos = {
        'estado': EjecucionIA.Estado.INVALIDA,
        'codigo_error': (codigo or 'respuesta_invalida')[:64],
        'detalle_error': texto_seguro(detalle, LARGO_DETALLE)[:LARGO_DETALLE],
    }
    if resultado is not None:
        campos['resultado'] = _json_seguro(resultado)
    return _actualizar(_id_de(respuesta_o_id), campos)


class Cronometro:
    """Milisegundos transcurridos desde su creación."""

    def __init__(self):
        self._inicio = time.monotonic()

    @property
    def ms(self):
        return int((time.monotonic() - self._inicio) * 1000)
