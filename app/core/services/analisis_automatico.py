"""Análisis automático de comentarios en segundo plano.

Al publicar o editar un comentario la vista llama a `programar_analisis`
después del commit. Eso sólo encola el id y responde enseguida: el análisis
(Ollama o léxico) corre en un hilo trabajador del mismo proceso, así la
respuesta HTTP nunca espera al modelo.

Garantías y límites:
- Un único hilo por proceso: las llamadas a Ollama se hacen de a una.
- Un comentario no se encola dos veces mientras espera; el trabajador relee
  el texto de la base, así una edición posterior se analiza con el texto
  actual y un comentario sin cambios se omite por hash (`analizar_comentario`).
- La cola vive en memoria: si el servidor se reinicia se pierde lo pendiente.
  El comando `analizar_sentimiento_comentarios` es el respaldo que recupera
  comentarios sin análisis, en error o analizados con léxico porque la IA falló.

Configuración por variables de entorno:
- SENTIMIENTO_COMENTARIOS_AUTOMATICO: "0" lo desactiva (por defecto activo).
- SENTIMIENTO_COMENTARIOS_METODO: "ia" (por defecto) o "lexicon".
"""
import logging
import os
import queue
import threading

from django.db import close_old_connections

from core.models import Comentario
from .sentimiento_comentarios import (
    METODO_IA,
    METODO_LEXICON,
    analizar_comentario,
    registrar_error_analisis,
)

logger = logging.getLogger(__name__)

_cola = queue.Queue()
_en_cola = set()
_candado = threading.Lock()
_hilo = None


def analisis_automatico_activo():
    return os.environ.get('SENTIMIENTO_COMENTARIOS_AUTOMATICO', '1').strip().lower() not in ('0', 'false', 'no')


def metodo_automatico():
    metodo = os.environ.get('SENTIMIENTO_COMENTARIOS_METODO', METODO_IA).strip().lower()
    return metodo if metodo in (METODO_IA, METODO_LEXICON) else METODO_IA


def procesar_comentario(comentario_id):
    """Analiza un comentario por id; nunca propaga excepciones al llamador.

    Relee el comentario de la base para usar siempre el texto actual.
    """
    try:
        comentario = Comentario.objects.select_related('sentimiento').filter(pk=comentario_id).first()
        if comentario is None:
            return None  # Borrado antes de procesarse.
        _, accion = analizar_comentario(comentario, usar_ia=metodo_automatico() == METODO_IA)
        return accion
    except Exception:  # noqa: BLE001 - el hilo no debe morir por un comentario.
        logger.exception('Falló el análisis automático del comentario %s.', comentario_id)
        try:
            # Conserva un análisis vigente; si no hay, deja el error para el comando de respaldo.
            registrar_error_analisis(Comentario(pk=comentario_id), 'excepcion_inesperada')
        except Exception:  # noqa: BLE001
            logger.exception('No se pudo registrar el error del comentario %s.', comentario_id)
        return 'error'


def _trabajador():
    while True:
        comentario_id = _cola.get()
        # Se libera antes de procesar: una edición que llegue mientras tanto
        # vuelve a encolarse y se analiza con el texto nuevo.
        with _candado:
            _en_cola.discard(comentario_id)
        # Conexión propia del hilo, abierta y cerrada como en un request de Django.
        close_old_connections()
        try:
            procesar_comentario(comentario_id)
        finally:
            close_old_connections()
            _cola.task_done()


def _enviar_a_segundo_plano(comentario_id):
    """Encola el id y arranca el hilo trabajador si hace falta. Las pruebas lo reemplazan."""
    global _hilo
    with _candado:
        if comentario_id in _en_cola:
            return False
        _en_cola.add(comentario_id)
        if _hilo is None or not _hilo.is_alive():
            # daemon: no retiene el apagado del servidor; lo pendiente lo recupera el comando.
            _hilo = threading.Thread(target=_trabajador, name='analisis-comentarios', daemon=True)
            _hilo.start()
    _cola.put(comentario_id)
    return True


def programar_analisis(comentario_id):
    """Pide el análisis de un comentario sin bloquear. Devuelve True si quedó encolado.

    Pensado para `transaction.on_commit` en las vistas: si algo falla al encolar,
    se registra y el comentario queda pendiente para el comando de respaldo,
    pero la publicación del usuario no se ve afectada.
    """
    if not analisis_automatico_activo():
        return False
    try:
        return _enviar_a_segundo_plano(comentario_id)
    except Exception:  # noqa: BLE001
        logger.exception('No se pudo encolar el análisis del comentario %s.', comentario_id)
        return False
