import json
from django.shortcuts import redirect, render, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.hashers import check_password
from django.utils import timezone 

# Importación de Modelos
from core.models import Publicacion, RegistroDatos, Sentimiento, Locacion, User

# Importación de Servicios
from core.services import scraper as scraper_service
from core.services.gemini_cliente import procesar_publicaciones_con_ia

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
@csrf_exempt
def crear_o_ingestar_publicacion(request):
    """ Crea publicaciones en lote extrayendo del RSS """
    if request.method == 'POST':
        try:
            body = json.loads(request.body)
            categoria = body.get('categoria', 'misiones')
            
            # Dispara el servicio de scraping
            noticias = fetch_elterritorio_news_by_category(category=categoria, limit=5)
            
            # Registro de Auditoría (RegistroDatos)
            registro = RegistroDatos.objects.create(
                fuentes_api=f"El Territorio ({categoria})",
                fecha_ejecucion=timezone.now(),
                estado="EXITO",
                lenguaje="es"
            )

            creadas = 0
            for item in noticias:
                # Deduplicación mediante Hash de Origen
                pub, created = Publicacion.objects.get_or_create(
                    hash_origen=item['id_noticia'],
                    defaults={
                        'fuente': item['source'],
                        'titulo': item['title'],
                        'contenido': item['summary'],
                        'url': item['link'],
                        'procesado_ia': False,
                        'id_registro': registro
                    }
                )
                if created:
                    creadas += 1

            return JsonResponse({
                "status": "success",
                "mensaje": f"Se procesaron las noticias. {creadas} nuevas creadas.",
                "id_registro": registro.id_registro
            }, status=201)

        except Exception as e:
            return JsonResponse({"status": "error", "detalle": str(e)}, status=400)
    return JsonResponse({"status": "error", "mensaje": "Método no permitido"}, status=405)


@csrf_exempt
def disparar_ingesta(request, categoria):
    """ Endpoint directo para ejecutar la función de ingesta general """
    resultado_ingesta = fetch_and_store_elterritorio(categoria)
    
    # 2. NUEVO: Ejecutar el Worker de IA para procesar lo recién ingresado
    # Batch_size alto para procesar todas las nuevas en la categoría (ej. 10)
    resultado_ia = procesar_publicaciones_con_ia(batch_size=10)
    
    return JsonResponse({
        "status": "success", 
        "mensaje_ingesta": resultado_ingesta,
        "mensaje_ia": resultado_ia
    })


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