import json
try:
    from google import genai  # type: ignore
    from google.genai import types  # type: ignore
except ImportError:  # pragma: no cover - compatibilidad con entornos sin la SDK nueva
    genai = None
    types = None

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from core.models import Publicacion, Sentimiento, Locacion
from core.services.scraper import fetch_and_store_elterritorio


SYSTEM_PROMPT = """
Eres el motor analítico de TrendWatch enfocado en el Litoral argentino.
Analiza la noticia recibida y responde ÚNICAMENTE en un formato JSON estricto con el siguiente esquema:
{
  "polaridad": float (número entre -1.0 para negativo, 0.0 para neutro y 1.0 para positivo),
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


class GeminiCliente:
    def __init__(self, api_key=None, model_name='gemini-1.5-pro'):
        self.model_name = model_name
        self.api_key = api_key or getattr(settings, 'GEMINI_API_KEY', None)
        self.client = None
        self.types = None

        if genai is not None and self.api_key:
            try:
                self.client = genai.Client(api_key=self.api_key)
                self.types = types
            except Exception as exc:  # pragma: no cover - si falla la inicialización
                print(f"No se pudo inicializar Gemini: {exc}")
                self.client = None
                self.types = None

    def procesar_publicaciones_con_ia(self, batch_size=5):
        if self.client is None or self.types is None:
            print("Gemini SDK no está disponible o faltan configuraciones.")
            return f"Se procesaron 0 publicaciones con {self.model_name}."

        pendientes = Publicacion.objects.filter(procesado_ia=False)[:batch_size]
        procesadas_count = 0

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

                raw_response = response.text
                if not raw_response:
                    raise ValueError("Gemini devolvió una respuesta vacía.")
                data = json.loads(raw_response)

                Sentimiento.objects.create(
                    polaridad=data.get('polaridad', 0.0),
                    confianza=data.get('confianza', 0.0),
                    id_publicacion_api=pub
                )

                for loc in data.get('localidades', []):
                    Locacion.objects.create(
                        location=loc.get('nombre', 'Desconocido')[:18],
                        latitud=loc.get('latitud', 0.0),
                        longitud=loc.get('longitud', 0.0),
                        id_publicacion_api=pub
                    )

                pub.procesado_ia = True
                pub.save()
                procesadas_count += 1

            except Exception as e:
                print(f"Error analizando publicación {pub.id_publicacion_api}: {e}")

        return f"Se procesaron {procesadas_count} publicaciones con {self.model_name}."


gemini_cliente = GeminiCliente()
client = gemini_cliente.client
types = gemini_cliente.types


def procesar_publicaciones_con_ia(batch_size=5):
    return gemini_cliente.procesar_publicaciones_con_ia(batch_size=batch_size)

@csrf_exempt
def disparar_ingesta(request, categoria):
    """ Endpoint directo para ejecutar la ingesta y luego la IA """
    
    # 1. Ejecutar el Scraper (como ya lo tenías)
    resultado_ingesta = fetch_and_store_elterritorio(categoria)
    
    # 2. NUEVO: Ejecutar el Worker de IA para procesar lo recién ingresado
    # Batch_size alto para procesar todas las nuevas en la categoría (ej. 10)
    resultado_ia = procesar_publicaciones_con_ia(batch_size=10)
    
    return JsonResponse({
        "status": "success", 
        "mensaje_ingesta": resultado_ingesta,
        "mensaje_ia": resultado_ia
    })