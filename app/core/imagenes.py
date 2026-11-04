"""Identifica placas genéricas del medio que no son fotos de una noticia."""

from urllib.parse import urlsplit


def es_portada_generica(url):
    if not url:
        return False
    partes = urlsplit(url)
    return (
        partes.hostname in {'elterritorio.com.ar', 'www.elterritorio.com.ar'}
        and partes.path.casefold().startswith('/images/custom/sin-imagen.')
    )
