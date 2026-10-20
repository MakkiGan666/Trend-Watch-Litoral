"""Validación de identidades nuevas; no reescribe usuarios históricos.

El bloqueo PostgreSQL coordina registro, perfil y UserAdmin. No es una
restricción de BD para escritores ORM/SQL que no participen del protocolo.
"""
from contextlib import contextmanager
from functools import wraps

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.db.models import Q


@contextmanager
def serializar_identidad():
    # Orden compartido: primero identidad, después la fila de usuario del perfil.
    # Dos enteros reservados para TrendWatch/identidad, dentro de esta base.
    with transaction.atomic():
        if connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_xact_lock(%s, %s)', [0x54574C, 0x4944])
        yield


def con_identidad_serializada(vista):
    @wraps(vista)
    def protegida(*args, **kwargs):
        with serializar_identidad():
            return vista(*args, **kwargs)
    return protegida


def errores_identidad(*, username=None, email=None, excluir_pk=None):
    """Consultar valores nuevos ya normalizados por su formulario/alta.

    No excluir inactivos: podrían volver a habilitarse. Una cuenta puede usar
    su propio username como email. Comparar en BD con iexact, como el login
    por email, sin convertir a minúsculas ni recortar datos almacenados.
    """
    usuarios = get_user_model()._default_manager.all()
    if excluir_pk is not None:
        usuarios = usuarios.exclude(pk=excluir_pk)
    errores = {}
    if username and usuarios.filter(email__iexact=username.strip()).exists():
        errores['username'] = 'Ese nombre de usuario coincide con el email de otra cuenta.'
    if email and usuarios.filter(
        Q(email__iexact=email.strip()) | Q(username__iexact=email.strip())
    ).exists():
        errores['email'] = 'Ese email ya está registrado o coincide con otro nombre de usuario.'
    return errores
