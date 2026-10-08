import json
import time 
try:
    from google import genai  # type: ignore
    from google.genai import types  # type: ignore
except ImportError:  # pragma: no cover - compatibilidad con entornos sin la SDK nueva
    genai = None
    types = None

from django.conf import settings
from django.db import transaction
from core.services.integridad_sentimiento import validar_numero as _numero_validado
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required, permission_required
from core.models import Publicacion, Sentimiento, Locacion
from core.services.scraper import fetch_and_store_elterritorio
from core.services.resultado_ia import respuesta_resultado_ia


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
    if not isinstance(raw_response, str) or not raw_response.strip():
        raise ValueError("Gemini devolvió una respuesta vacía o no textual.")

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


class ConflictoResultadoIA(ValueError):
    def __init__(self, codigo):
        self.codigo = codigo
        super().__init__(codigo)


class GeminiCliente:
    def __init__(self, api_key=None, model_name='gemini-3.8-flash'):
        self.model_name = model_name
        self.api_key = api_key or getattr(settings, 'GEMINI_API_KEY', None)
        self.client = None
        self.types = None

        if genai is not None and self.api_key:
            try:
                self.client = genai.Client(api_key=self.api_key)
                self.types = types
            except Exception:  # pragma: no cover - si falla la inicialización
                print("No se pudo inicializar Gemini.")
                self.client = None
                self.types = None

    def procesar_publicaciones_con_ia(self, batch_size=5):
        return self.procesar_pendientes(batch_size=batch_size)

    def procesar_pendientes(self, batch_size=5):
        # Evaluar antes de comprobar disponibilidad: un fallo de consulta se propaga.
        pendientes = list(Publicacion.objects.filter(procesado_ia=False)[:batch_size])
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
        if self.client is None or self.types is None:
            for pub in pendientes:
                registrar_error(pub, 'servicio_no_disponible')
            resultado['estado'] = 'NO_DISPONIBLE'
            resultado['mensaje'] = 'El servicio Gemini no está disponible.'
            return resultado

        for pub in pendientes:
            prompt = f"Título: {pub.titulo}\nContenido: {pub.contenido}"

            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=self.types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        temperature=0.1
                    )
                )

            except Exception:
                registrar_error(pub, 'llamada_gemini')
                continue

            try:
                data = validar_respuesta_gemini(response.text)
            except (ValueError, TypeError, AttributeError, RecursionError):
                registrar_error(pub, 'validacion_respuesta')
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
                    resultado['omitidas'] += 1
                    continue
                resultado['procesadas'] += 1

            except ConflictoResultadoIA as error:
                registrar_error(pub, error.codigo)
                continue
            except Exception:
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
@permission_required(('core.ejecutar_scraping', 'core.procesar_ia'), raise_exception=True)
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
