import json
from django.shortcuts import redirect, render, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.hashers import check_password
from django.utils import timezone 
import hashlib

# REST Framework
from rest_framework.views import APIView
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

# Modelos y Serializadores
from core.models import Publicacion, RegistroDatos, Sentimiento, Locacion, User
from .serializers import UserMeSerializer

# Servicios (Scrapers, Sentiment & Gemini)
from core.services import scraper as scraper_service
from .services.scraper import fetch_and_store_elterritorio
from core.services.gemini_cliente import procesar_publicaciones_con_ia
from .services.sentimiento import analyze_sentiment_lexicon, compute_probabilistic_sentiment
_fetch_elterritorio_news_by_category = getattr(
    scraper_service,
    'fetch_elterritorio_news_by_category',
    None,
)
if _fetch_elterritorio_news_by_category is not None:
    fetch_elterritorio_news_by_category = _fetch_elterritorio_news_by_category
else:
    def fetch_elterritorio_news_by_category(*args, **kwargs) -> list[dict]:
        raise NotImplementedError(
            'La función fetch_elterritorio_news_by_category no está disponible en core.services.scraper.'
        )

_fetch_and_store_elterritorio = getattr(
    scraper_service,
    'fetch_and_store_elterritorio',
    None,
)
if _fetch_and_store_elterritorio is not None:
    fetch_and_store_elterritorio = _fetch_and_store_elterritorio
else:
    def fetch_and_store_elterritorio(*args, **kwargs) -> str:
        raise NotImplementedError(
            'La función fetch_and_store_elterritorio no está disponible en core.services.scraper.'
        )


# ==========================================
# VISTAS WEB Y PLANTILLAS HTML
# ==========================================

def landing(request):
    return render(request, 'inicio.html')


def categorias(request):
    return render(request, 'categorias.html')


def litoral(request):
    return render(request, 'litoral.html')


def login_view(request):
    if request.session.get('user_id'):
        return render(request, 'login.html', {'already_logged_in': True})

    error = None
    if request.method == 'POST':
        identifier = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        user = User.objects.filter(email__iexact=identifier).first()
        if user is None:
            user = User.objects.filter(nombre__iexact=identifier).first()

        if user is not None and check_password(password, user.password_hash):
            request.session.cycle_key()
            request.session['user_id'] = user.id_user
            request.session['user_name'] = user.nombre
            request.session['user_email'] = user.email
            return redirect('landing')

        error = 'Usuario o contraseña incorrectos.'
    return render(request, 'login.html', {'error': error})


def logout_view(request):
    request.session.flush()
    return redirect('landing')


def dashboard(request):
    # Traemos las publicaciones y usamos prefetch_related para traer también sus sentimientos 
    # (esto optimiza la base de datos en lugar de hacer una consulta por cada fila)
    publicaciones = Publicacion.objects.select_related('id_registro')\
                                       .prefetch_related('sentimiento_set', 'locacion_set')\
                                       .order_by('-fecha', '-id_publicacion_api')[:100]
    
    return render(request, 'core/dashboard.html', {
        'publicaciones': publicaciones,
    })

def procesar_ia(request):
    """ Endpoint web para disparar manualmente la IA """
    resultado = procesar_publicaciones_con_ia(batch_size=10)
    return JsonResponse({
        "status": "success", 
        "mensaje": resultado
    })

# ==========================================
# ENDPOINTS API REST (CRUD)
# ==========================================

# 1. CREATE / INGESTA
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def crear_o_ingestar_publicacion(request):
    """
    Crea una publicación (manual o RSS) y le calcula automáticamente el sentimiento.
    """
    data = request.data
    
    # CASO A: Creación manual vía JSON
    if data and "titulo" in data and "contenido" in data:
        # 1. Guardar la publicación en PostgreSQL
        url_val = data.get("url", "")
        
        # Si la URL viene vacía, usamos el título para garantizar que no choque
        base_hash = url_val if url_val else data.get("titulo", "")
        hash_gen = hashlib.sha256(base_hash.encode('utf-8')).hexdigest()
    
        publicacion = Publicacion.objects.create(
            hash_origen=hash_gen,
            titulo=data.get("titulo"),
            contenido=data.get("contenido"),
            fuente=data.get("fuente", "Manual"),
            url=data.get("url", ""),
            fecha_captura=data.get("fecha_publicacion", timezone.now())
        )
        
        # 2. CALCULAR SENTIMIENTO AUTOMÁTICAMENTE
        texto_analizar = f"{publicacion.titulo} {publicacion.contenido}"
        polaridad = float(analyze_sentiment_lexicon(texto_analizar))
        
        analisis_lote = compute_probabilistic_sentiment([{"message": texto_analizar}])
        confianza = float(analisis_lote.get("confidence_score", 0.0))

        # 3. Guardar en la tabla Sentimiento
        obj_sentimiento, _ = Sentimiento.objects.update_or_create(
            id_publicacion_api=publicacion,
            defaults={
                'polaridad': polaridad,
                'confianza': confianza,
            }
        )

        # 4. Marcar como procesada por la IA
        publicacion.procesado_ia = True
        publicacion.save()

        # 5. Retornar la respuesta con el sentimiento incluido
        return Response({
            "status": "ok",
            "id_publicacion_api": publicacion.id_publicacion_api,
            "titulo": publicacion.titulo,
            "procesado_ia": publicacion.procesado_ia,
            "sentimiento": {
                "id_sentimiento": obj_sentimiento.id_sentimiento,
                "polaridad": obj_sentimiento.polaridad,
                "confianza": obj_sentimiento.confianza
            },
            "mensaje": "Publicación creada e ingerida con análisis de sentimiento automático."
        }, status=status.HTTP_201_CREATED)

    # CASO B: Ingesta masiva vía Scraper RSS
    else:
        publicaciones_creadas = fetch_and_store_elterritorio()
        
        for pub in publicaciones_creadas:
            if not pub.procesado_ia:
                texto = f"{pub.titulo} {pub.contenido}"
                pol = float(analyze_sentiment_lexicon(texto))
                
                res_prob = compute_probabilistic_sentiment([{"message": texto}])
                conf = float(res_prob.get("confidence_score", 0.0))

                Sentimiento.objects.update_or_create(
                    id_publicacion_api=pub,
                    defaults={'polaridad': pol, 'confianza': conf}
                )
                pub.procesado_ia = True
                pub.save()

        return Response({
            "status": "ok",
            "total_ingestadas": len(publicaciones_creadas),
            "mensaje": f"Se procesaron {len(publicaciones_creadas)} publicaciones RSS con sentimiento automatizado."
        }, status=status.HTTP_200_OK)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def disparar_ingesta(request, categoria):
    """ Endpoint directo para ejecutar la función de ingesta general """
    resultado_ingesta = fetch_and_store_elterritorio(categoria)
    resultado_ia = procesar_publicaciones_con_ia(batch_size=10)
    
    return Response({
        "status": "success", 
        "mensaje_ingesta": resultado_ingesta,
        "mensaje_ia": resultado_ia
    }, status=status.HTTP_200_OK)


# 2. READ (Lectura)
def listar_publicaciones(request):
    """ Retorna un listado JSON con las últimas 20 publicaciones y sus análisis de sentimiento """
    if request.method == 'GET':
        publicaciones = Publicacion.objects.all().order_by('-fecha_captura')[:20]
        
        data = []
        for p in publicaciones:
            sentimiento_obj = Sentimiento.objects.filter(id_publicacion_api=p).first()
            
            data.append({
                "id": p.id_publicacion_api,
                "titulo": p.titulo,
                "fuente": p.fuente,
                "url": p.url,
                "procesado_ia": p.procesado_ia,
                "fecha": p.fecha_captura.strftime("%Y-%m-%d %H:%M:%S") if p.fecha_captura else None,
                "sentimiento": {
                    "polaridad": sentimiento_obj.polaridad if sentimiento_obj else None,
                    "confianza": sentimiento_obj.confianza if sentimiento_obj else None
                } if sentimiento_obj else None
            })

        return JsonResponse({"status": "success", "total": len(data), "data": data})
    return JsonResponse({"status": "error", "mensaje": "Método no permitido"}, status=405)


def obtener_detalle_publicacion(request, pk):
    """ Obtiene el detalle de una publicación con sus locaciones geográficas """
    if request.method == 'GET':
        pub = get_object_or_404(Publicacion, pk=pk)
        locaciones = list(Locacion.objects.filter(id_publicacion_api=pub).values('location', 'latitud', 'longitud'))
        
        return JsonResponse({
            "id": pub.id_publicacion_api,
            "titulo": pub.titulo,
            "contenido": pub.contenido,
            "fuente": pub.fuente,
            "url": pub.url,
            "procesado_ia": pub.procesado_ia,
            "locaciones": locaciones
        })
    return JsonResponse({"status": "error", "mensaje": "Método no permitido"}, status=405)


# 3. UPDATE (Actualización / Moderación)
@csrf_exempt
def actualizar_publicacion(request, pk):
    """ Modifica campos de una publicación recibiendo un JSON """
    if request.method in ['PUT', 'PATCH']:
        pub = get_object_or_404(Publicacion, pk=pk)
        try:
            body = json.loads(request.body)
            
            if 'titulo' in body:
                pub.titulo = body['titulo']
            if 'contenido' in body:
                pub.contenido = body['contenido']
            if 'procesado_ia' in body:
                pub.procesado_ia = body['procesado_ia']

            pub.save()
            return JsonResponse({"status": "success", "mensaje": f"Publicación {pk} actualizada."})

        except Exception as e:
            return JsonResponse({"status": "error", "detalle": str(e)}, status=400)
    return JsonResponse({"status": "error", "mensaje": "Método no permitido"}, status=405)


# 4. DELETE (Eliminación)
@csrf_exempt
def eliminar_publicacion(request, pk):
    """ Elimina una publicación por ID """
    if request.method == 'DELETE':
        pub = get_object_or_404(Publicacion, pk=pk)
        pub.delete()
        return JsonResponse({"status": "success", "mensaje": f"Publicación {pk} eliminada exitosamente."})
    return JsonResponse({"status": "error", "mensaje": "Método no permitido"}, status=405)

class UserMeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserMeSerializer(request.user)
        return Response(serializer.data)
    
    
class BatchSentimentAnalysisView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request):
        """
        Espera un payload JSON con una lista de comentarios:
        {
          "comments": [
            {"message": "El servicio es excelente e impecable"},
            {"message": "Muy malo y con muchos problemas"}
          ]
        }
        """
        comments = request.data.get('comments', [])
        
        if not isinstance(comments, list):
            return Response(
                {"error": "El campo 'comments' debe ser una lista de objetos."}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        # Ejecutamos el análisis probabilístico
        metrics = compute_probabilistic_sentiment(comments)
        return Response(metrics, status=status.HTTP_200_OK)
    

class ProcesarSentimientoPublicacionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        """
        Analiza el texto de una publicación específica de la DB 
        y registra/actualiza el resultado en la tabla Sentimiento.
        """
        publicacion = get_object_or_404(Publicacion, pk=pk)
        
        # 1. Unimos el título y contenido para el análisis
        texto_analizar = f"{publicacion.titulo} {publicacion.contenido}"
        
        # 2. Calculamos la polaridad léxica individual (convertida a float nativo)
        polaridad = float(analyze_sentiment_lexicon(texto_analizar))
        
        # 3. Calculamos la métrica probabilística (convertida a float nativo)
        analisis_lote = compute_probabilistic_sentiment([{"message": texto_analizar}])
        confianza = float(analisis_lote.get("confidence_score", 0.0))

        # 4. Guardamos o actualizamos en la tabla Sentimiento de PostgreSQL
        obj_sentimiento, created = Sentimiento.objects.update_or_create(
            id_publicacion_api=publicacion,
            defaults={
                'polaridad': polaridad,
                'confianza': confianza,
            }
        )

        # 5. Marcamos la publicación como procesada por la IA
        publicacion.procesado_ia = True
        publicacion.save()

        return Response({
            "id_publicacion": publicacion.id_publicacion_api,
            "titulo": publicacion.titulo,
            "procesado_ia": publicacion.procesado_ia,
            "sentimiento": {
                "id_sentimiento": obj_sentimiento.id_sentimiento,
                "polaridad": obj_sentimiento.polaridad,
                "confianza": obj_sentimiento.confianza
            }
        }, status=status.HTTP_200_OK)
