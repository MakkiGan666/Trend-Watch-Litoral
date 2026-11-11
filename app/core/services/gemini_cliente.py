import json
import logging
import os
import re
import time
try:
    from google import genai  # type: ignore
    from google.genai import errors as genai_errors  # type: ignore
    from google.genai import types  # type: ignore
except ImportError:  # pragma: no cover - compatibilidad con entornos sin la SDK nueva
    genai = None
    genai_errors = None
    types = None
try:
    import httpx  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - llega como dependencia de google-genai
    httpx = None

from django.conf import settings
from django.db import transaction
from core.services.integridad_sentimiento import validar_numero as _numero_validado
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required, permission_required
from core.models import Publicacion, Sentimiento, Locacion
from core.services.scraper import fetch_and_store_elterritorio
from core.services.resultado_ia import respuesta_resultado_ia
from core.services.parametros import entero_positivo
from core.services.ia.base import Solicitud
from core.services.ia import seguimiento
from core.services.ia.gestor import obtener_gestor

logger = logging.getLogger(__name__)

MODELO_POR_DEFECTO = 'gemini-3.8-flash'
# Espera máxima de una respuesta de Gemini; superado, el pedido cuenta como fallo temporal
# (y habilita el respaldo con Ollama si el administrador lo activó). GEMINI_TIMEOUT lo ajusta.
TIMEOUT_POR_DEFECTO = 60.0
# Sólo los fallos temporales se reintentan: 3 intentos en total, con esperas de 2 y 4 segundos.
MAX_INTENTOS = 3
ESPERAS_REINTENTO = (2, 4)
# Un 429 se reintenta únicamente si Google sugiere una espera corta (RetryInfo).
MAX_RETRY_DELAY = 30
_CODIGOS_SERVIDOR_TEMPORALES = {500, 502, 503, 504}
_FORMATO_RETRY_DELAY = re.compile(r'^(\d+(?:\.\d+)?)s$')

# Mensaje del proveedor en el log: breve y sin nada que parezca una credencial.
LARGO_MAX_MENSAJE = 160
_OCULTO = '[oculto]'
_PATRONES_SENSIBLES = (
    re.compile(r'AIza[0-9A-Za-z_\-]{20,}'),                     # API keys de Google
    re.compile(r'ya29\.[0-9A-Za-z_\-.]+'),                      # tokens OAuth de Google
    re.compile(r'\bBearer\s+\S+', re.IGNORECASE),
    re.compile(r'\b(?:x-goog-api-key|api[_-]?key|key|token|access_token|password|secret)\s*[=:]\s*\S+',
               re.IGNORECASE),
    re.compile(r'[A-Za-z0-9_\-+/=]{32,}'),                      # cadenas opacas largas
)
# Un fragmento de este largo coincidente con el prompt indica que el mensaje repite la noticia.
_LARGO_FRAGMENTO_PROMPT = 24


SYSTEM_PROMPT = """
Eres el motor analítico de TrendWatch enfocado en el Litoral argentino.
Analiza la noticia recibida y responde ÚNICAMENTE en un formato JSON estricto con el siguiente esquema:
Todos los campos son obligatorios. No agregues propiedades adicionales en ningún objeto.
Los números deben ser finitos: polaridad en [-1, 1], confianza en [0, 1],
latitud en [-90, 90] y longitud en [-180, 180]. No uses cadenas, booleanos ni null.
Los nombres de localidad deben ser textos no vacíos de máximo 18 caracteres.
No repitas un nombre de localidad, incluso si sus coordenadas son diferentes.
La comparación de nombres es exacta. Si no hay localidades, devuelve una lista vacía.
{
  "polaridad": float (número entre -1.0 para negativo, 0.0 para neutr   o y 1.0 para positivo),
  "confianza": float (número entre 0.0 y 1.0),
  "localidades": [
    {
      "nombre": string (ej: "Posadas", "Garupá", "Oberá"),
      "latitud": float (aprox. latitud geográfica si corresponde o 0.0),
      "longitud": float (aprox. longitud geográfica si corresponde o 0.0)
    }
  ]
}
"""


def validar_respuesta_gemini(raw_response):
    """Valida todo el resultado antes de permitir cualquier escritura."""
    if not isinstance(raw_response, str) or len(raw_response) > 256 * 1024 or not raw_response.strip():
        raise ValueError("Gemini devolvió una respuesta vacía, excesiva o no textual.")

    def objeto_sin_duplicados(pares):
        objeto = {}
        for clave, valor in pares:
            if clave in objeto:
                raise ValueError(f"Campo JSON duplicado: {clave}.")
            objeto[clave] = valor
        return objeto

    data = json.loads(raw_response, object_pairs_hook=objeto_sin_duplicados)
    if not isinstance(data, dict) or set(data) != {'polaridad', 'confianza', 'localidades'}:
        raise ValueError("La respuesta debe contener polaridad, confianza y localidades únicamente.")
    polaridad = _numero_validado(data['polaridad'], 'polaridad', -1, 1)
    confianza = _numero_validado(data['confianza'], 'confianza', 0, 1)
    if not isinstance(data['localidades'], list):
        raise ValueError("localidades debe ser una lista.")
    localidades = []
    nombres = set()
    for loc in data['localidades']:
        if not isinstance(loc, dict) or set(loc) != {'nombre', 'latitud', 'longitud'}:
            raise ValueError("Cada localidad debe contener nombre, latitud y longitud únicamente.")
        nombre = loc['nombre']
        if not isinstance(nombre, str) or not nombre.strip() or len(nombre) > 18:
            raise ValueError("nombre debe ser un texto no vacío de hasta 18 caracteres.")
        if nombre in nombres:
            raise ValueError("Localidad duplicada en la respuesta.")
        nombres.add(nombre)
        localidades.append({
            'nombre': nombre,
            'latitud': _numero_validado(loc['latitud'], 'latitud', -90, 90),
            'longitud': _numero_validado(loc['longitud'], 'longitud', -180, 180),
        })
    return {'polaridad': polaridad, 'confianza': confianza, 'localidades': localidades}


def _detalles_error(exc):
    """Lista `error.details` del cuerpo de un APIError (RetryInfo, QuotaFailure, ErrorInfo...)."""
    datos = getattr(exc, 'details', None)
    if isinstance(datos, dict) and isinstance(datos.get('error'), dict):
        datos = datos['error']
    detalles = datos.get('details') if isinstance(datos, dict) else None
    return [d for d in detalles if isinstance(d, dict)] if isinstance(detalles, list) else []


def _del_tipo(detalle, nombre):
    return str(detalle.get('@type', '')).endswith(f'google.rpc.{nombre}')


def _retry_delay(detalles):
    """Segundos sugeridos por RetryInfo ("39s", "1.5s"), o None si no hay un valor válido."""
    for detalle in detalles:
        if _del_tipo(detalle, 'RetryInfo'):
            coincidencia = _FORMATO_RETRY_DELAY.match(str(detalle.get('retryDelay', '')).strip())
            if coincidencia:
                return float(coincidencia.group(1))
    return None


def _cuota_diaria_agotada(detalles):
    for detalle in detalles:
        if _del_tipo(detalle, 'QuotaFailure'):
            for violacion in detalle.get('violations') or []:
                if isinstance(violacion, dict) and 'perday' in str(violacion.get('quotaId', '')).lower():
                    return True
    return False


def clasificar_error_gemini(exc):
    """Devuelve (tipo, codigo_http, temporal, espera_sugerida) sin leer contenido de la noticia.

    Sólo `temporal=True` habilita reintentos. Ante la duda (p. ej. un 429 sin
    RetryInfo) el error se trata como definitivo.
    """
    if httpx is not None and isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
        return 'red', None, True, None
    if genai_errors is None or not isinstance(exc, genai_errors.APIError):
        return 'desconocido', None, False, None
    codigo = exc.code
    estado = str(exc.status or '')
    detalles = _detalles_error(exc)
    if codigo in _CODIGOS_SERVIDOR_TEMPORALES:
        return 'no_disponible', codigo, True, None
    if codigo == 429:
        if _cuota_diaria_agotada(detalles):
            return 'cuota_agotada', codigo, False, None
        espera = _retry_delay(detalles)
        if espera is not None and espera <= MAX_RETRY_DELAY:
            return 'limite_frecuencia', codigo, True, espera
        return 'limite_no_determinado', codigo, False, None
    clave_invalida = codigo == 400 and (
        'api key' in str(exc.message or '').lower()
        or any(d.get('reason') == 'API_KEY_INVALID' for d in detalles)
    )
    if codigo in (401, 403) or estado in ('UNAUTHENTICATED', 'PERMISSION_DENIED') or clave_invalida:
        return 'autenticacion', codigo, False, None
    if codigo == 404:
        return 'modelo_inexistente', codigo, False, None
    return 'error_definitivo', codigo, False, None


def mensaje_error_seguro(exc, prompt='', api_key=None):
    """Mensaje breve del proveedor apto para el log, o None si no se puede garantizar.

    Sólo se toma `APIError.message` (el texto que Google arma para el error), nunca
    el cuerpo HTTP ni mensajes de excepciones ajenas al SDK. Se normalizan los
    espacios, se enmascaran credenciales y tokens y se recorta a LARGO_MAX_MENSAJE.
    Si el mensaje repite parte del prompt (título o contenido) se descarta entero.
    """
    if genai_errors is None or not isinstance(exc, genai_errors.APIError):
        return None
    mensaje = getattr(exc, 'message', None)
    if not isinstance(mensaje, str):
        return None
    mensaje = ' '.join(''.join(c if c.isprintable() else ' ' for c in mensaje).split())
    if not mensaje:
        return None
    if api_key:
        mensaje = mensaje.replace(api_key, _OCULTO)
    for patron in _PATRONES_SENSIBLES:
        mensaje = patron.sub(_OCULTO, mensaje)
    if prompt:
        sin_marcas = mensaje.replace(_OCULTO, ' ')
        for inicio in range(max(len(sin_marcas) - _LARGO_FRAGMENTO_PROMPT + 1, 0)):
            if sin_marcas[inicio:inicio + _LARGO_FRAGMENTO_PROMPT] in prompt:
                return None
    if len(mensaje) > LARGO_MAX_MENSAJE:
        mensaje = mensaje[:LARGO_MAX_MENSAJE - 1].rstrip() + '…'
    # Defensa final: si tras enmascarar aún queda la clave, no se registra nada.
    if api_key and api_key in mensaje:
        return None
    return mensaje


def _timeout_gemini():
    """Segundos de espera configurados (GEMINI_TIMEOUT); un valor inválido usa el predeterminado."""
    try:
        valor = float(os.environ.get('GEMINI_TIMEOUT', TIMEOUT_POR_DEFECTO))
        return valor if 0 < valor <= 600 else TIMEOUT_POR_DEFECTO
    except (TypeError, ValueError):
        return TIMEOUT_POR_DEFECTO


class ConflictoResultadoIA(ValueError):
    def __init__(self, codigo):
        self.codigo = codigo
        super().__init__(codigo)


class GeminiCliente:
    def __init__(self, api_key=None, model_name=None):
        self.model_name = model_name or getattr(settings, 'GEMINI_MODEL', '') or MODELO_POR_DEFECTO
        self.api_key = api_key or getattr(settings, 'GEMINI_API_KEY', None)
        self.client = None
        self.types = None

        if genai is not None and self.api_key:
            try:
                self.client = genai.Client(
                    api_key=self.api_key,
                    http_options=types.HttpOptions(timeout=int(_timeout_gemini() * 1000)),
                )
                self.types = types
            except Exception:  # pragma: no cover - si falla la inicialización
                print("No se pudo inicializar Gemini.")
                self.client = None
                self.types = None

    def procesar_publicaciones_con_ia(self, batch_size=5):
        return self.procesar_pendientes(batch_size=batch_size)

    def _sufijo_mensaje(self, exc, prompt):
        mensaje = mensaje_error_seguro(exc, prompt=prompt, api_key=self.api_key)
        return f' mensaje="{mensaje}"' if mensaje else ''

    def _generar_con_reintentos(self, pub_pk, prompt):
        """Llama a Gemini; reintenta sólo fallos temporales y relanza el último error.

        Nada se persiste aquí: un reintento nunca duplica resultados.
        """
        for intento in range(1, MAX_INTENTOS + 1):
            try:
                assert self.client is not None
                assert self.types is not None
                return self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=self.types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        temperature=0.1
                    )
                )
            except Exception as exc:
                tipo, codigo, temporal, espera = clasificar_error_gemini(exc)
                reintenta = temporal and intento < MAX_INTENTOS
                # Sólo metadatos del error y, si es seguro, el mensaje breve del proveedor.
                logger.warning(
                    'Gemini falló: publicacion=%s intento=%d/%d tipo=%s codigo_http=%s estado=%s reintento=%s%s',
                    pub_pk, intento, MAX_INTENTOS, tipo, codigo, getattr(exc, 'status', None) or '-',
                    'si' if reintenta else 'no', self._sufijo_mensaje(exc, prompt),
                )
                if not reintenta:
                    raise
                time.sleep(espera if espera is not None else ESPERAS_REINTENTO[intento - 1])

    def procesar_pendientes(self, batch_size=5, desde=None, hasta=None):
        """Procesa un lote de pendientes; `desde`/`hasta` (fechas, inclusive) acotan por fecha de publicación."""
        entero_positivo(batch_size, 'batch_size')
        consulta = Publicacion.objects.filter(procesado_ia=False)
        if desde is not None:
            consulta = consulta.filter(fecha_publicacion__date__gte=desde)
        if hasta is not None:
            consulta = consulta.filter(fecha_publicacion__date__lte=hasta)
        # Evaluar antes de comprobar disponibilidad: un fallo de consulta se propaga.
        pendientes = list(consulta[:batch_size])
        resultado = {
            'estado': 'SIN_PENDIENTES', 'seleccionadas': len(pendientes),
            'procesadas': 0, 'omitidas': 0, 'fallidas': 0, 'errores': [],
            'mensaje': 'No hay publicaciones pendientes en el lote.',
        }

        def registrar_error(pub, codigo):
            resultado['fallidas'] += 1
            resultado['errores'].append({'id_publicacion_api': pub.pk, 'codigo': codigo})

        if not pendientes:
            return resultado
        # El gestor central decide el motor (Gemini u Ollama) y el respaldo automático. Gemini
        # conserva sus reintentos ante fallos temporales; sólo si se agotan se prueba el alternativo.
        gestor = obtener_gestor(cliente_gemini=self, reintentos_gemini=True)
        principal = gestor.principal()
        if not principal.persiste_analisis_publicaciones:
            # Los análisis de publicaciones (sentimiento y coordenadas) sólo se guardan con un
            # motor validado como equivalente a Gemini. Ni siquiera se consulta al motor local:
            # sus resultados se descartarían. Las publicaciones siguen pendientes.
            logger.warning(
                'Gemini: lote=%d resultado=fallida codigo=motor_no_persistente proveedor=%s',
                len(pendientes), principal.nombre,
            )
            for pub in pendientes:
                registrar_error(pub, 'motor_no_persistente')
            resultado['estado'] = 'NO_DISPONIBLE'
            resultado['mensaje'] = ('El motor principal configurado no guarda análisis de publicaciones; '
                                    'elegí Gemini en el panel de Motor de Inteligencia Artificial.')
            return resultado
        if not gestor.disponible():
            for pub in pendientes:
                registrar_error(pub, 'servicio_no_disponible')
            resultado['estado'] = 'NO_DISPONIBLE'
            resultado['mensaje'] = 'El motor de IA configurado no está disponible.'
            return resultado

        for pub in pendientes:
            prompt = f"Título: {pub.titulo}\nContenido: {pub.contenido}"

            try:
                # La generación no escribe en la base: el resultado se persiste recién tras validarlo.
                response = gestor.generar(Solicitud(
                    system=SYSTEM_PROMPT, contenido=prompt, tarea='analisis_publicacion',
                    esperado='objeto', referencia=pub.pk, entidad='publicacion',
                ))
            except Exception as exc:
                logger.error(
                    'Gemini: publicacion=%s resultado=fallida codigo=llamada_gemini tipo=%s%s',
                    pub.pk, clasificar_error_gemini(exc)[0], self._sufijo_mensaje(exc, prompt),
                )
                registrar_error(pub, 'llamada_gemini')
                continue

            if not gestor.persiste_analisis_publicaciones(response.proveedor):
                # Defensa en profundidad: aunque el motor principal sea persistible, el resultado
                # de un proveedor que no lo es (p. ej. Llama como respaldo) nunca se guarda y la
                # publicación sigue pendiente hasta que responda un motor persistible.
                codigo = 'respaldo_no_persistido' if response.respaldo else 'motor_no_persistente'
                logger.warning(
                    'Gemini: publicacion=%s resultado=fallida codigo=%s proveedor=%s',
                    pub.pk, codigo, response.proveedor,
                )
                registrar_error(pub, codigo)
                seguimiento.registrar_resultado(response, {'guardado': False, 'motivo': codigo})
                continue

            try:
                assert response is not None
                data = validar_respuesta_gemini(response.text)
            except (ValueError, TypeError, AttributeError, RecursionError) as exc:
                logger.warning(
                    'Gemini: publicacion=%s resultado=fallida codigo=validacion_respuesta tipo=%s',
                    pub.pk, type(exc).__name__,
                )
                registrar_error(pub, 'validacion_respuesta')
                seguimiento.marcar_invalida(response, 'validacion_respuesta', type(exc).__name__)
                continue

            omitida = False
            try:
                with transaction.atomic():
                    publicacion = Publicacion.objects.select_for_update().get(pk=pub.pk)
                    if publicacion.procesado_ia:
                        omitida = True
                    else:
                        sentimientos = list(Sentimiento.objects.filter(
                            id_publicacion_api=publicacion,
                        )[:2])
                        if len(sentimientos) > 1:
                            raise ConflictoResultadoIA('sentimientos_multiples')
                        if Locacion.objects.filter(id_publicacion_api=publicacion).exists():
                            raise ConflictoResultadoIA('locaciones_preexistentes')

                        if sentimientos:
                            sentimiento = sentimientos[0]
                            sentimiento.polaridad = data['polaridad']
                            sentimiento.confianza = data['confianza']
                            sentimiento.save(update_fields=['polaridad', 'confianza'])
                        else:
                            Sentimiento.objects.create(
                                polaridad=data['polaridad'],
                                confianza=data['confianza'],
                                id_publicacion_api=publicacion,
                            )
                        for loc in data['localidades']:
                            Locacion.objects.create(
                                location=loc['nombre'],
                                latitud=loc['latitud'],
                                longitud=loc['longitud'],
                                id_publicacion_api=publicacion,
                            )
                        publicacion.procesado_ia = True
                        publicacion.save(update_fields=['procesado_ia'])
                if omitida:
                    logger.info('Gemini: publicacion=%s resultado=omitida', pub.pk)
                    resultado['omitidas'] += 1
                    seguimiento.registrar_resultado(response, {**data, 'guardado': False, 'motivo': 'ya_procesada'})
                    continue
                logger.info('Gemini: publicacion=%s resultado=procesada', pub.pk)
                resultado['procesadas'] += 1
                seguimiento.registrar_resultado(response, {**data, 'guardado': True})

            except ConflictoResultadoIA as error:
                logger.warning('Gemini: publicacion=%s resultado=fallida codigo=%s', pub.pk, error.codigo)
                registrar_error(pub, error.codigo)
                seguimiento.registrar_resultado(response, {**data, 'guardado': False, 'motivo': error.codigo})
                continue
            except Exception as exc:
                # Sólo la clase: el mensaje de la base puede incluir valores de la fila.
                logger.error(
                    'Gemini: publicacion=%s resultado=fallida codigo=persistencia tipo=%s',
                    pub.pk, type(exc).__name__,
                )
                registrar_error(pub, 'persistencia')
                continue

            # Política post-commit: continuar el lote si falla la espera ordinaria.
            # El resultado confirmado permanece procesado; no se reintenta ni se
            # registra como fallo de IA. KeyboardInterrupt/SystemExit se propagan.
            try:
                time.sleep(12)
            except Exception:
                continue

        if resultado['fallidas'] == 0:
            resultado['estado'] = 'EXITO'
        elif resultado['procesadas'] + resultado['omitidas']:
            resultado['estado'] = 'PARCIAL'
        else:
            resultado['estado'] = 'FALLO'
        resultado['mensaje'] = (
            f"Lote IA: {resultado['procesadas']} procesadas, "
            f"{resultado['omitidas']} omitidas y {resultado['fallidas']} fallidas."
        )
        return resultado


gemini_cliente = GeminiCliente()
client = gemini_cliente.client
types = gemini_cliente.types


def procesar_publicaciones_con_ia(batch_size=5):
    return gemini_cliente.procesar_publicaciones_con_ia(batch_size=batch_size)

@require_POST
@login_required(login_url='login')
@permission_required(('core.ejecutar_scraping', 'core.procesar_ia'), raise_exception=True) # type: ignore
def disparar_ingesta(request, categoria):
    """ Endpoint directo para ejecutar la ingesta y luego la IA """
    
    # 1. Ejecutar el Scraper (como ya lo tenías)
    resultado_ingesta = fetch_and_store_elterritorio(categoria)
    
    # 2. NUEVO: Ejecutar el Worker de IA para procesar lo recién ingresado
    # Batch_size alto para procesar todas las nuevas en la categoría (ej. 10)
    
    if resultado_ingesta.get('status') != 'EXITO':
        return JsonResponse({
            'status': 'error',
            'mensaje': 'La ingesta RSS falló; puede haber publicaciones guardadas parcialmente.',
            'mensaje_ingesta': resultado_ingesta,
        }, status=500)
    resultado_ia = procesar_publicaciones_con_ia(batch_size=10)
    data, codigo_http = respuesta_resultado_ia(
        resultado_ia, campo_mensaje='mensaje_ia', mensaje_ingesta=resultado_ingesta,
    )
    return JsonResponse(data, status=codigo_http)
