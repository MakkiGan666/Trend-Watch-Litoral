"""Servidor de revisión sólo para el contenedor creado por el launcher hermano."""
import os
import secrets
import sys
import socket
import types
from datetime import timedelta

if os.environ.get('TW_FRONT_PREVIEW_AISLADO') != '1':
    raise SystemExit('Usar previsualizar_busqueda.sh iniciar; no admite bases externas.')
def sin_salida(self, address):
    raise PermissionError('La previsualización bloquea conexiones salientes')

socket.socket.connect = sin_salida
socket.socket.connect_ex = sin_salida

os.environ.update(DJANGO_SETTINGS_MODULE='mi_proyecto.settings', PYTHON_DOTENV_DISABLED='1',
                  SECRET_KEY=secrets.token_urlsafe(48), DB_HOST='', GEMINI_API_KEY='', DEBUG='True',
                  ALLOWED_HOSTS='127.0.0.1,localhost,testserver')
sys.path.insert(0, '/app')
from django.conf import settings
settings.DATABASES['default']['NAME'] = '/tmp/preview_busqueda.sqlite3'
import django
django.setup()
from django.core.management import call_command
from django.contrib.auth import get_user_model, login
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import include, path
from django.utils import timezone
from core.models import Publicacion

call_command('migrate', interactive=False, verbosity=0)
ahora = timezone.now()
titulos = [
    'Educación: nuevas aulas para las escuelas de Misiones',
    'La educación pública reúne propuestas de toda la provincia',
    'Docentes y familias conversan sobre educación y tecnología',
    'Más oportunidades de educación en las localidades del Litoral',
]
Publicacion.objects.bulk_create([
    Publicacion(hash_origen=f'preview-{i}', titulo=titulos[i % len(titulos)],
                contenido=('Las comunidades de Misiones comparten sus propuestas. '*8) +
                          ' La educación abre nuevas oportunidades para niños y jóvenes de la región. '+
                          ('Familias y docentes participan de encuentros en sus localidades. '*12),
                fuente='Fuente sintética · Demostración', fecha_captura=ahora-timedelta(hours=i),
                fecha_publicacion=None if i % 4 == 0 else ahora-timedelta(hours=i),
                imagen_url='/preview/imagen.svg' if i % 3 == 0 else ('/preview/inexistente.jpg' if i % 7 == 0 else ''))
    for i in range(43)
])
usuario = get_user_model().objects.create_user(username='lectora_demo')

def sesion(request):
    login(request, usuario, backend='django.contrib.auth.backends.ModelBackend')
    return redirect('/buscar/?q=educacion')


def imagen(request):
    return HttpResponse('<svg xmlns="http://www.w3.org/2000/svg" width="560" height="400" viewBox="0 0 560 400"><rect width="560" height="400" fill="#163832"/><circle cx="440" cy="90" r="48" fill="#8eb69b"/><path d="M0 280 160 100 350 300 470 200 560 300V400H0" fill="#235347"/><path d="M250 0Q130 180 330 400H440Q230 190 380 0" fill="#3fd0b4" opacity=".5"/></svg>', content_type='image/svg+xml')

urlconf = types.ModuleType('tw_preview_urls')
urlconf.urlpatterns = [
    path('preview/sesion/', sesion), path('preview/imagen.svg', imagen),
    # La portada nunca consulta un servicio de cotizaciones real en esta revisión.
    path('api/cotizaciones/', lambda request: JsonResponse({'status': 'unavailable', 'cotizaciones': []})),
    path('', include('mi_proyecto.urls')),
]
sys.modules[urlconf.__name__] = urlconf
settings.ROOT_URLCONF = urlconf.__name__
print('Previsualización: 43 noticias sintéticas, SQLite temporal, migraciones aplicadas.', flush=True)
call_command('runserver', '0.0.0.0:8000', use_reloader=False)
