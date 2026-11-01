from django.urls import path
from . import views
from .views_buscador import buscar_publicaciones, buscar_noticias
from . import views_comentarios
from . import views_valoraciones
from . import views_perfil
from . import views_dashboard
from .views_administradores import gestion_administradores
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from .views import (
    UserMeView,
    BatchSentimentAnalysisView,
    ProcesarSentimientoPublicacionView,
    crear_publicacion_view
)

urlpatterns = [
    path('administradores/', gestion_administradores, name='gestion_administradores'),
    path('buscar/', buscar_noticias, name='buscar_noticias'),
    path('perfil/', views_perfil.perfil, name='perfil'),
    path('perfil/guardados/', views_perfil.perfil, {'seccion': 'guardados'}, name='mis_guardados'),
    path('perfil/notificaciones/', views_perfil.perfil, {'seccion': 'notificaciones'}, name='perfil_notificaciones'),
    path('noticia/<int:pk>/guardar/', views_perfil.guardar_publicacion, name='guardar_publicacion'),
    # Vistas Web / Templates
    path('', views.landing, name='landing'),
    path('categorias/', views.categorias, name='categorias'),
    path('noticia/<int:pk>/', views.noticia, name='noticia'),
    path('noticia/<int:pk>/comentarios/', views_comentarios.crear_comentario, name='crear_comentario'),
    path('noticia/<int:pk>/valoracion/', views_valoraciones.valorar_noticia, name='valorar_noticia'),
    path('comentarios/<int:pk>/editar/', views_comentarios.editar_comentario, name='editar_comentario'),
    path('comentarios/<int:pk>/eliminar/', views_comentarios.eliminar_comentario, name='eliminar_comentario'),
    path('litoral/', views.litoral, name='litoral'),
    path('localidad/<slug:slug>/', views.localidad, name='localidad'),
    path('api/localidades/<slug:slug>/publicaciones/', views.publicaciones_localidad, name='publicaciones_localidad'),
    path('login/', views.login_view, name='login'),
    path('registro/', views.registro_view, name='registro'),
    path('logout/', views.logout_view, name='logout'),
    path('publicaciones/', views.publicaciones, name='publicaciones'),
    path('dashboard/', views_dashboard.dashboard, name='dashboard'),
    path('procesar-ia/', views.procesar_ia, name='procesar_ia'),

    # API REST - CRUD de Publicaciones
    path('api/publicaciones/buscar/', buscar_publicaciones, name='buscar_publicaciones'),
    path('api/publicaciones/crear/', views.crear_o_ingestar_publicacion, name='crear_publicacion'),
    path('api/publicaciones/ingestar/<str:categoria>/', views.disparar_ingesta, name='disparar_ingesta'),
    path('api/publicaciones/', views.listar_publicaciones, name='listar_publicaciones'),
    path('api/cotizaciones/', views.cotizaciones, name='cotizaciones'),
    path('api/publicaciones/<int:pk>/', views.obtener_detalle_publicacion, name='detalle_publicacion'),
    path('api/publicaciones/<int:pk>/actualizar/', views.actualizar_publicacion, name='actualizar_publicacion'),
    path('api/publicaciones/<int:pk>/eliminar/', views.eliminar_publicacion, name='eliminar_publicacion'),

    # Autenticación
    path('api/auth/login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/auth/logout/', views.LogoutJWTView.as_view(), name='jwt_logout'),
    
    # Perfil de usuario
    path('api/auth/me/', UserMeView.as_view(), name='user_me'),
    
    # Análisis de Sentimiento e IA
    path('api/sentiment/batch-analyze/', BatchSentimentAnalysisView.as_view(), name='sentiment_batch_analyze'),
    path('api/publicaciones/<int:pk>/procesar-sentimiento/', ProcesarSentimientoPublicacionView.as_view(), name='procesar_sentimiento_publicacion'),

    # Panel web de gestión de noticias (sesión del sitio)
    path('publicaciones/crear/', crear_publicacion_view, name='crear_publicacion_web'),
    path('publicaciones/<int:pk>/editar/', views.editar_publicacion_view, name='editar_publicacion_web'),
    path('publicaciones/<int:pk>/eliminar/', views.eliminar_publicacion_view, name='eliminar_publicacion_web'),
]
