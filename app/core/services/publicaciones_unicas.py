"""Oculta copias editoriales en listados sin borrar publicaciones de la base."""

from datetime import timedelta

from django.utils.text import slugify


PALABRAS_DE_ENLACE = {
    'a', 'al', 'ante', 'como', 'con', 'de', 'del', 'el', 'en', 'es', 'fue',
    'la', 'las', 'lo', 'los', 'para', 'por', 'se', 'su', 'sus', 'un', 'una',
    'unos', 'unas', 'y',
}


def _palabras(titulo):
    return tuple(
        palabra for palabra in slugify(titulo or '').split('-')
        if palabra and palabra not in PALABRAS_DE_ENLACE
    )


def _es_copia(palabras, fecha, anteriores):
    if not fecha:
        return False
    conjunto = set(palabras)
    for otras_palabras, otra_fecha in anteriores:
        if not otra_fecha or abs(fecha - otra_fecha) > timedelta(days=2):
            continue
        if palabras == otras_palabras:
            return True
        if len(palabras) < 7 or len(otras_palabras) < 7:
            continue
        otro_conjunto = set(otras_palabras)
        if len(conjunto & otro_conjunto) / len(conjunto | otro_conjunto) >= 0.75:
            return True
    return False


def ids_publicaciones_unicas(registros):
    """Recibe (id, título, fecha_publicación, fecha_captura) en orden de preferencia."""
    visibles = []
    grupos = {}
    for pk, titulo, fecha_publicacion, fecha_captura in registros:
        palabras = _palabras(titulo)
        # Los títulos cortos, como «Agenda», pueden describir entregas distintas.
        if len(palabras) < 3:
            visibles.append(pk)
            continue
        clave = palabras[:4]
        fecha = fecha_publicacion or fecha_captura
        anteriores = grupos.setdefault(clave, [])
        if _es_copia(palabras, fecha, anteriores):
            continue
        anteriores.append((palabras, fecha))
        visibles.append(pk)
    return visibles


def publicaciones_unicas(publicaciones, limite=None):
    """Filtra una secuencia de objetos ya ordenada, conservando el primero."""
    visibles = []
    grupos = {}
    for publicacion in publicaciones:
        palabras = _palabras(publicacion.titulo)
        if len(palabras) < 3:
            visibles.append(publicacion)
        else:
            clave = palabras[:4]
            fecha = publicacion.fecha_publicacion or publicacion.fecha_captura
            anteriores = grupos.setdefault(clave, [])
            if _es_copia(palabras, fecha, anteriores):
                continue
            anteriores.append((palabras, fecha))
            visibles.append(publicacion)
        if limite is not None and len(visibles) == limite:
            break
    return visibles
