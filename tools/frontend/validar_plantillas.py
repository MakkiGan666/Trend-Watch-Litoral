"""Renderiza fixtures y ejecuta tests con /app de solo lectura y SQLite en memoria."""
import os
import re
import secrets
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

os.environ.update(
    SECRET_KEY=secrets.token_urlsafe(32),
    DJANGO_SETTINGS_MODULE='mi_proyecto.settings',
    DB_HOST='', DEBUG='True', PYTHONDONTWRITEBYTECODE='1',
)
sys.path.insert(0, '/app')

from django.conf import settings

settings.DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
settings.STATIC_URL = '/static/'
settings.PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

import django

django.setup()

from django import forms
from django.contrib.auth.models import AnonymousUser
from django.core.management import call_command
from django.template.loader import render_to_string
from django.test import RequestFactory


def render_fixtures():
    output = Path('/evidence')
    request = RequestFactory().get('/')
    request.user = AnonymousUser()

    class Dates(forms.Form):
        desde = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
        hasta = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))

    form = Dates({'desde': '2026-10-01', 'hasta': '2026-10-31'})
    html = render_to_string('core/dashboard.html', {
        'request': request, 'filtros': form, 'resumen': {'total': 0},
    }, request=request)
    (output / 'dashboard.html').write_text(html)
    (output / 'dashboard-nojs.html').write_text(re.sub(
        r'<script\b[^>]*>.*?</script>', '', html, flags=re.S,
    ))
    html = render_to_string('core/publicaciones.html', {
        'request': request, 'resumen': {'total': 0}, 'fecha_seleccionada': '2026-01-15',
    }, request=request)
    (output / 'publicaciones.html').write_text(html)
    for name, size in [
        ('vertical', (400, 1800)), ('horizontal', (1600, 900)),
        ('pequena', (80, 60)), ('ausente', None), ('fallida', None),
    ]:
        image = ''
        if size:
            width, height = size
            image = 'data:image/svg+xml,' + quote(
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
                '<rect width="100%" height="100%" fill="#235347"/></svg>'
            )
        if name == 'fallida':
            image = '/missing-image.png'
        html = render_to_string('noticia.html', {
            'request': request,
            'publicacion': SimpleNamespace(pk=1, titulo='Noticia sintética de validación', fuente='Demo local'),
            'imagen_noticia': image, 'credito_imagen': 'Demo',
            'contenido_noticia': ('Texto de demostración para comprobar lectura y expansión. ' * 25 + '\n\n') * 6,
        }, request=request)
        (output / f'{name}.html').write_text(html)
    print('FIXTURES_OK')


if __name__ == '__main__':
    if sys.argv[1:] == ['test']:
        call_command('check')
        call_command('test', 'core.test_new_dashboard', 'core.test_publicaciones_paginacion',
                     'core.test_dashboard_localidades', verbosity=1)
    else:
        render_fixtures()
