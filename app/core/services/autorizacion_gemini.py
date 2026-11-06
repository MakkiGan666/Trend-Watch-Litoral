"""Autorización explícita de Gemini para publicaciones del catálogo RSS."""
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from core.services.fuentes_rss import FUENTES_RSS


def fuentes_autorizadas():
    valor = getattr(settings, 'GEMINI_MULTIFUENTE_FUENTES_AUTORIZADAS', ())
    if not isinstance(valor, (tuple, list)) or any(not isinstance(item, str) for item in valor):
        raise ImproperlyConfigured('GEMINI_MULTIFUENTE_FUENTES_AUTORIZADAS debe ser una lista de IDs.')
    catalogo = {fuente.identificador: fuente for fuente in FUENTES_RSS}
    if len(set(valor)) != len(valor) or any(item not in catalogo for item in valor):
        raise ImproperlyConfigured('La autorización Gemini contiene IDs duplicados o ajenos al catálogo RSS.')
    return frozenset(valor)


def fuente_autorizada(identificador):
    return identificador in fuentes_autorizadas()


def publicacion_multifuente_autorizada(publicacion):
    fuente = next((f for f in FUENTES_RSS if f.nombre == getattr(publicacion, 'fuente', None)), None)
    return fuente is not None and fuente_autorizada(fuente.identificador)


def es_publicacion_multifuente(publicacion):
    """Clasifica por la identidad editorial persistida, sin depender del recibo."""
    return getattr(publicacion, 'fuente', None) in {fuente.nombre for fuente in FUENTES_RSS}
