"""Oculta copias editoriales en listados sin borrar publicaciones de la base."""

from datetime import datetime, timedelta, timezone

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


def _admitir(grupos, palabras, fecha):
    """Indexa sólo noticias visibles; no presupone orden cronológico de entrada."""
    if len(palabras) < 3 or not fecha:
        return True
    dia = fecha.toordinal()
    margen = 2
    if isinstance(fecha, datetime):
        offset = fecha.utcoffset()
        if offset is not None:
            hora_utc = timedelta(hours=fecha.hour, minutes=fecha.minute,
                                 seconds=fecha.second, microseconds=fecha.microsecond) - offset
            dia += hora_utc.days
            # Python resta horas civiles si ambos datetimes tienen la misma zona.
            # Un margen conservador contempla cambios de offset sin perder pares;
            # _es_copia sigue comprobando los dos días exactos del contrato.
            if not isinstance(fecha.tzinfo, timezone):
                margen = 4
    dias = grupos.setdefault(palabras[:4], {})
    anteriores = (
        registro
        for candidato in range(dia - margen, dia + margen + 1)
        for registro in dias.get(candidato, ())
    )
    if _es_copia(palabras, fecha, anteriores):
        return False
    dias.setdefault(dia, []).append((palabras, fecha))
    return True


def ids_publicaciones_unicas(registros):
    """Recibe (id, título, fecha_publicación, fecha_captura) en orden de preferencia."""
    visibles = []
    grupos = {}
    for pk, titulo, fecha_publicacion, fecha_captura in registros:
        if _admitir(grupos, _palabras(titulo), fecha_publicacion or fecha_captura):
            visibles.append(pk)
    return visibles


def publicaciones_unicas(publicaciones, limite=None):
    """Filtra una secuencia de objetos ya ordenada, conservando el primero."""
    visibles = []
    grupos = {}
    for publicacion in publicaciones:
        if not _admitir(grupos, _palabras(publicacion.titulo),
                        publicacion.fecha_publicacion or publicacion.fecha_captura):
            continue
        visibles.append(publicacion)
        if limite is not None and len(visibles) == limite:
            break
    return visibles
