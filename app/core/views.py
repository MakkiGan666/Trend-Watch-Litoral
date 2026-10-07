import json
import hashlib
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db.models import Count, F
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.hashers import check_password
from django.contrib.auth.decorators import login_required

# REST Framework
from rest_framework.views import APIView
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

# Modelos y Formularios
from core.models import (
    Publicacion, RegistroDatos, Sentimiento, Locacion, 
    User, TemaTrend, Tema, PublicacionTema
)
from .forms import PublicacionForm
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

from django.db.models import Count
from core.models import TemaTrend

def landing(request):
    """
    Carga la portada (inicio.html) enviando las tendencias/temas destacados
    y calculando el total de publicaciones por cada tema.
    """
    featured_trends = TemaTrend.objects.select_related(
        'id_temas', 
        'id_trends', 
        'id_temas__id_categoria'
    ).annotate(
        publication_count=Count('id_temas__publicaciones')
    ).all()[:6]

    return render(request, 'inicio.html', {
        'featured_trends': featured_trends,
    })


def categorias(request):
    return render(request, 'categorias.html')


def litoral(request):
    return render(request, 'litoral.html')


def login_view(request):
    # Si ya está logueado, redirige directamente al inicio
    if request.user.is_authenticated:
        return redirect('landing')

    if request.method == 'POST':
        identifier = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        
        user = authenticate(request, username=identifier, password=password)
        
        if user is not None:
            login(request, user)
            return redirect('landing')
        else:
            # Si falla el login, recarga inicio.html pasando las tendencias y abriendo el modal con error
            featured_trends = TemaTrend.objects.select_related(
                'id_temas', 'id_trends', 'id_temas__id_categoria'
            ).annotate(publication_count=Count('id_temas__publicaciones')).all()[:6]

            return render(request, 'inicio.html', {
                'featured_trends': featured_trends,
                'open_login_modal': True,
                'login_error': 'Usuario o contraseña incorrectos.',
            })

    # Si entran por GET a /login/, redirigimos a la portada
    return redirect('landing')


def logout_view(request):
    logout(request) # Limpia la sesión
    return redirect('landing')


@login_required(login_url='login')
def dashboard(request):
    """ Muestra el panel con las publicaciones, sentimientos y locaciones """
    publicaciones = Publicacion.objects.select_related('id_registro')\
                                       .prefetch_related('sentimiento_set', 'locacion_set')\
                                       .order_by('-fecha_captura', '-id_publicacion_api')[:100]
    
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

def crear_publicacion_view(request):
    if request.method == 'POST':
        form = PublicacionForm(request.POST)
        if form.is_valid():
            publicacion = form.save(commit=False)
            
            # Generar hash_origen si está vacío
            if not publicacion.hash_origen:
                semilla = f"{publicacion.titulo}{timezone.now().timestamp()}"
                publicacion.hash_origen = hashlib.sha256(semilla.encode('utf-8')).hexdigest()
            
            publicacion.save()

            # Vincular la categoría seleccionada a través de Tema
            categoria_seleccionada = form.cleaned_data.get('categoria')
            if categoria_seleccionada:
                # Buscar si ya existe algún Tema para esta categoría
                tema = Tema.objects.filter(id_categoria=categoria_seleccionada).first()
                
                # Si no existe ninguno, creamos uno nuevo
                if not tema:
                    tema = Tema.objects.create(
                        id_categoria=categoria_seleccionada,
                        descripcion=f'Tema automático para {categoria_seleccionada.nombre_categoria}'
                    )

                # Crear el vínculo en la tabla intermedia
                PublicacionTema.objects.create(
                    id_publicacion_api=publicacion,
                    id_temas=tema
                )

            return redirect('landing')
    else:
        form = PublicacionForm()

    return render(request, 'core/crear_publicacion.html', {'form': form})