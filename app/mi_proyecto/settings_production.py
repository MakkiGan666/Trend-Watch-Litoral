"""Activar explícitamente con DJANGO_SETTINGS_MODULE; nunca cargar .env local."""
import os
from django.core.exceptions import ImproperlyConfigured
from .production_config import production_config

try:
    _production = production_config(os.environ)
except ValueError as error:
    raise ImproperlyConfigured(str(error)) from None

from .settings import *  # noqa: E402,F403 - conservar contratos de la aplicación

globals().update(_production)
