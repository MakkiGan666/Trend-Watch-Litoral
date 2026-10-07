from django.urls import path
from . import views
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from .views import (
    UserMeView,
    BatchSentimentAnalysisView,
    ProcesarSentimientoPublicacionView,
)

urlpatterns = [
    # Vistas Web / Templates
    path('', views.landing, name='landing'),
    path('categorias/', views.categorias, name='categorias'),
    path('noticia/<int:pk>/', views.noticia, name='noticia'),
    path('litoral/', views.litoral, name='litoral'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('procesar-ia/', views.procesar_ia, name='procesar_ia'),

    # API REST - CRUD de Publicaciones
    path('api/publicaciones/crear/', views.crear_o_ingestar_publicacion, name='crear_publicacion'),
    path('api/publicaciones/ingestar/<str:categoria>/', views.disparar_ingesta, name='disparar_ingesta'),
    path('api/publicaciones/', views.listar_publicaciones, name='listar_publicaciones'),
    path('api/publicaciones/<int:pk>/', views.obtener_detalle_publicacion, name='detalle_publicacion'),
    path('api/publicaciones/<int:pk>/actualizar/', views.actualizar_publicacion, name='actualizar_publicacion'),
    path('api/publicaciones/<int:pk>/eliminar/', views.eliminar_publicacion, name='eliminar_publicacion'),

    # Autenticación
    path('api/auth/login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    
    # Perfil de usuario
    path('api/auth/me/', UserMeView.as_view(), name='user_me'),
    
    # Análisis de Sentimiento
    path('api/sentiment/batch-analyze/', BatchSentimentAnalysisView.as_view(), name='sentiment_batch_analyze'),
    
    # Análisis de Sentimiento e IA
    path('api/sentiment/batch-analyze/', BatchSentimentAnalysisView.as_view(), name='sentiment_batch_analyze'),
    path('api/publicaciones/<int:pk>/procesar-sentimiento/', ProcesarSentimientoPublicacionView.as_view(), name='procesar_sentimiento_publicacion'),
]
