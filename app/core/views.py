import json
import hashlib
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.db import IntegrityError, connection, transaction
from django.db.models import Count, F
from django.contrib.auth import login, logout
from django.contrib.auth.hashers import check_password
import re
from html import unescape
from urllib.parse import urlsplit
from django.utils.html import strip_tags
from django.views.decorators.http import require_safe, require_POST
from django.http import Http404
from .localidades import DEPARTAMENTOS, departamento_de_ubicacion
from .services.cotizaciones import obtener_cotizaciones
from django.contrib.auth.decorators import login_required, permission_required

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
from .services.autenticacion import autenticar_identificador, ERROR_CREDENCIALES
from .serializers import PublicacionCreateSerializer, PublicacionUpdateSerializer, UserMeSerializer
from .permissions import CrearPublicacion, EditarPublicacion, EliminarPublicacion, EjecutarIngesta, ProcesarIA

# Servicios (Scrapers, Sentiment & Gemini)
from core.services import scraper as scraper_service
from .services.scraper import fetch_and_store_elterritorio
from core.services.gemini_cliente import procesar_publicaciones_con_ia
from core.services.resultado_ia import respuesta_resultado_ia
from .services.sentimiento import analyze_sentiment_lexicon, compute_probabilistic_sentiment
from .services.integridad_sentimiento import (
    ConflictoSentimiento, confianza_desde_porcentaje, guardar_sentimiento_local, sentimiento_unico,
)


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


@require_safe
def cotizaciones(request):
    return JsonResponse(obtener_cotizaciones())


@require_safe
def noticia(request, pk):
    """Lectura interna de una publicación existente, sin disparar ingesta ni IA."""
    publicacion = get_object_or_404(Publicacion, pk=pk)
    categorias_noticia = list(dict.fromkeys(
        publicacion.temas.values_list('id_categoria__nombre_categoria', flat=True)
    ))
    if not categorias_noticia:
        coincidencia = re.search(r'\(([^)]+)\)\s*$', publicacion.fuente or '')
        if coincidencia:
            categorias_noticia = [coincidencia.group(1).strip()]
    localidades_noticia = list(dict.fromkeys(
        Locacion.objects.filter(id_publicacion_api=publicacion)
        .exclude(location='').values_list('location', flat=True)
    ))

    def enlace_seguro(valor):
        try:
            url = (valor or '').strip()
            partes = urlsplit(url)
            return url if partes.scheme in ('http', 'https') and partes.netloc else None
        except (TypeError, ValueError, AttributeError):
            return None

    return render(request, 'noticia.html', {
        'publicacion': publicacion,
        'categorias_noticia': categorias_noticia,
        'localidades_noticia': localidades_noticia,
        'contenido_noticia': unescape(strip_tags(publicacion.contenido or '')).strip(),
        'imagen_noticia': enlace_seguro(getattr(publicacion, 'imagen_url', None)),
        'enlace_original': enlace_seguro(publicacion.url),
    })


def litoral(request):
    return render(request, 'litoral.html')


def _departamento_o_404(slug):
    departamento = next((d for d in DEPARTAMENTOS if d['slug'] == slug), None)
    if departamento is None:
        raise Http404('Departamento no encontrado')
    return departamento


@require_safe
def localidad(request, slug):
    return render(request, 'localidad.html', {'departamento': _departamento_o_404(slug)})


@require_safe
def publicaciones_localidad(request, slug):
    departamento = _departamento_o_404(slug)
    ubicaciones = [nombre for nombre in Locacion.objects.values_list('location', flat=True).distinct()
                   if departamento_de_ubicacion(nombre) == slug]
    publicaciones = (Publicacion.objects.filter(locacion__location__in=ubicaciones)
                     .distinct().prefetch_related('temas__id_categoria')
                     .order_by('-fecha_captura', '-id_publicacion_api'))
    data = []
    for publicacion in publicaciones:
        categorias = list(dict.fromkeys(t.id_categoria.nombre_categoria for t in publicacion.temas.all()))
        if not categorias:
            coincidencia = re.search(r'\(([^)]+)\)\s*$', publicacion.fuente or '')
            categorias = [coincidencia.group(1).strip()] if coincidencia else []
        data.append({
            'id': publicacion.id_publicacion_api,
            'titulo': publicacion.titulo,
            'fuente': publicacion.fuente,
            'url': publicacion.url,
            'categorias': categorias,
            'fecha': publicacion.fecha_captura.isoformat() if publicacion.fecha_captura else None,
        })
    return JsonResponse({'status': 'success', 'departamento': departamento['nombre'],
                         'total': len(data), 'data': data})


def login_view(request):
    # Si ya está logueado, redirige directamente al inicio
    if request.user.is_authenticated:
        return redirect('landing')

    if request.method == 'POST':
        identifier = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        
        user = autenticar_identificador(request, identifier, password)
        
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
                'login_error': ERROR_CREDENCIALES,
                'login_identifier': identifier,
            })

    # Si entran por GET a /login/, redirigimos a la portada
    return redirect('landing')


def logout_view(request):
    logout(request) # Limpia la sesión
    return redirect('landing')


@login_required(login_url='login')
@permission_required('core.view_publicacion', raise_exception=True)
def dashboard(request):
    """ Muestra el panel con las publicaciones, sentimientos y locaciones """
    publicaciones = Publicacion.objects.select_related('id_registro')\
                                       .prefetch_related('sentimiento_set', 'locacion_set')\
                                       .order_by('-fecha_captura', '-id_publicacion_api')[:100]
    
    return render(request, 'core/dashboard.html', {
        'publicaciones': publicaciones,
    })


@require_POST
@login_required(login_url='login')
@permission_required('core.procesar_ia', raise_exception=True)
def procesar_ia(request):
    """ Endpoint web para disparar manualmente la IA """
    resultado = procesar_publicaciones_con_ia(batch_size=10)
    data, codigo_http = respuesta_resultado_ia(resultado)
    return JsonResponse(data, status=codigo_http)

# ==========================================
# ENDPOINTS API REST (CRUD)
# ==========================================

# 1. CREATE / INGESTA
def _es_colision_hash_origen(error):
    diagnostico = getattr(error.__cause__, 'diag', None)
    tabla = Publicacion._meta.db_table
    if (connection.vendor != 'postgresql'
            or getattr(diagnostico, 'sqlstate', None) != '23505'
            or getattr(diagnostico, 'table_name', None) != tabla):
        return False
    with connection.cursor() as cursor:
        restricciones = connection.introspection.get_constraints(cursor, tabla)
    restriccion = restricciones.get(getattr(diagnostico, 'constraint_name', None), {})
    return (restriccion.get('unique', False)
            and not restriccion.get('primary_key', False)
            and restriccion.get('columns') == [Publicacion._meta.get_field('hash_origen').column])


def _respuesta_publicacion_duplicada(publicacion):
    data = {
        'status': 'error',
        'codigo': 'publicacion_duplicada',
        'mensaje': 'Ya existe una publicación con esta identidad.',
    }
    if publicacion is not None:
        data['id_publicacion_api'] = publicacion.pk
    return Response(data, status=status.HTTP_409_CONFLICT)


@api_view(['POST'])
@permission_classes([IsAuthenticated, CrearPublicacion])
def crear_o_ingestar_publicacion(request):
    """Crea una publicación manual y calcula automáticamente su sentimiento."""
    serializer = PublicacionCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    # Sin URL, títulos iguales comparten identidad aunque cambie el contenido.
    # El hash representa el origen: editar el título no lo regenera.
    base_hash = data['url'] or data['titulo']
    hash_gen = hashlib.sha256(base_hash.encode('utf-8')).hexdigest()
    existente = Publicacion.objects.filter(hash_origen=hash_gen).first()
    if existente is not None:
        return _respuesta_publicacion_duplicada(existente)
    try:
        with transaction.atomic():
            publicacion = Publicacion.objects.create(
                hash_origen=hash_gen,
                titulo=data['titulo'],
                contenido=data['contenido'],
                fuente=data['fuente'],
                url=data['url'],
                fecha_captura=data['fecha_publicacion'],
            )
            # El alta, el resultado local y el estado forman una única operación.
            texto_analizar = f"{publicacion.titulo} {publicacion.contenido}"
            polaridad = float(analyze_sentiment_lexicon(texto_analizar))
            confianza = confianza_desde_porcentaje(
                compute_probabilistic_sentiment([{"message": texto_analizar}]),
            )
            obj_sentimiento = guardar_sentimiento_local(publicacion, polaridad, confianza)
            publicacion.procesado_ia = True
            publicacion.save(update_fields=['procesado_ia'])
    except IntegrityError as error:
        # Consultar sólo después de salir del bloque y restaurar la transacción.
        if not _es_colision_hash_origen(error):
            raise
        existente = Publicacion.objects.filter(hash_origen=hash_gen).first()
        return _respuesta_publicacion_duplicada(existente)

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

@api_view(['POST'])
@permission_classes([IsAuthenticated, EjecutarIngesta])
def disparar_ingesta(request, categoria):
    """ Endpoint directo para ejecutar la función de ingesta general """
    resultado_ingesta = fetch_and_store_elterritorio(categoria)
    if resultado_ingesta.get('status') != 'EXITO':
        return Response({
            'status': 'error',
            'mensaje': 'La ingesta RSS falló; puede haber publicaciones guardadas parcialmente.',
            'mensaje_ingesta': resultado_ingesta,
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    resultado_ia = procesar_publicaciones_con_ia(batch_size=10)
    
    data, codigo_http = respuesta_resultado_ia(
        resultado_ia, campo_mensaje='mensaje_ia', mensaje_ingesta=resultado_ingesta,
    )
    return Response(data, status=codigo_http)


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
@api_view(['PUT', 'PATCH'])
@permission_classes([IsAuthenticated, EditarPublicacion])
def actualizar_publicacion(request, pk):
    """ Modifica campos de una publicación recibiendo un JSON """
    if request.method in ['PUT', 'PATCH']:
        pub = get_object_or_404(Publicacion, pk=pk)
        serializer = PublicacionUpdateSerializer(
            data=request.data, partial=request.method == 'PATCH',
        )
        serializer.is_valid(raise_exception=True)
        for campo, valor in serializer.validated_data.items():
            setattr(pub, campo, valor)
        pub.save()
        return JsonResponse({"status": "success", "mensaje": f"Publicación {pk} actualizada."})
    return JsonResponse({"status": "error", "mensaje": "Método no permitido"}, status=405)


# 4. DELETE (Eliminación)
@api_view(['DELETE'])
@permission_classes([IsAuthenticated, EliminarPublicacion])
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
    permission_classes = [IsAuthenticated, ProcesarIA]
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
    permission_classes = [IsAuthenticated, ProcesarIA]

    def post(self, request, pk):
        """
        Analiza el texto de una publicación específica de la DB 
        y registra/actualiza el resultado en la tabla Sentimiento.
        """
        try:
            with transaction.atomic():
                publicacion = get_object_or_404(Publicacion.objects.select_for_update(), pk=pk)
                sentimiento_unico(publicacion)
                texto_analizar = f"{publicacion.titulo} {publicacion.contenido}"
                polaridad = float(analyze_sentiment_lexicon(texto_analizar))
                confianza = confianza_desde_porcentaje(
                    compute_probabilistic_sentiment([{"message": texto_analizar}]),
                )
                obj_sentimiento = guardar_sentimiento_local(publicacion, polaridad, confianza)
                publicacion.procesado_ia = True
                publicacion.save(update_fields=['procesado_ia'])
        except ConflictoSentimiento:
            return Response({
                'status': 'error', 'codigo': 'sentimientos_multiples',
                'mensaje': 'La publicación tiene múltiples sentimientos; requiere revisión.',
            }, status=status.HTTP_409_CONFLICT)

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

@login_required(login_url='login')
@permission_required('core.add_publicacion', raise_exception=True)
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
