"""Completa asociaciones faltantes para artículos con cuerpo completo."""

from django.db import transaction
from django.db.models import Exists, OuterRef

from core.models import Publicacion, PublicacionEtiqueta, PublicacionTema
from core.services.clasificacion import (
    VERSION_CLASIFICACION_LOCAL, categoria_local_confirmada, vincular_categoria_por_nombre,
)
from core.services.etiquetas import guardar_etiquetas_propuestas, sugerir_etiquetas
from core.services.procedencia_analitica import Metodo, procedencia


def _candidatas():
    return Publicacion.objects.con_cuerpo_completo().only('titulo', 'contenido', 'contenido_completo').annotate(
        tiene_categoria=Exists(PublicacionTema.objects.filter(id_publicacion_api_id=OuterRef('pk'))),
        tiene_etiquetas=Exists(PublicacionEtiqueta.objects.filter(publicacion_id=OuterRef('pk'))),
    )


def lote_pendiente(cursor, limite):
    publicaciones = _candidatas().filter(pk__gt=cursor).exclude(
        tiene_categoria=True, tiene_etiquetas=True,
    ).order_by('pk')
    lote = list(publicaciones[:limite + 1])
    return lote[:limite], len(lote) > limite


def _proponer(publicacion):
    categoria = (None if publicacion.tiene_categoria
                 else categoria_local_confirmada(publicacion.titulo, publicacion.contenido))
    etiquetas = ([] if publicacion.tiene_etiquetas
                 else sugerir_etiquetas(publicacion.titulo, publicacion.contenido))
    estado_categoria = 'conservada' if publicacion.tiene_categoria else 'abstencion'
    estado_etiquetas = 'conservadas' if publicacion.tiene_etiquetas else 'sin_propuestas'
    return {
        'id': publicacion.pk,
        'clasificacion': 'propuesta' if categoria else estado_categoria,
        'categoria': categoria,
        'etiquetado': 'propuesto' if etiquetas else estado_etiquetas,
        'etiquetas': [slug for slug, _ in etiquetas],
    }, etiquetas


def simular(publicacion):
    resultado, _ = _proponer(publicacion)
    return resultado


@transaction.atomic
def aplicar(publicacion_id):
    # En PostgreSQL una única sentencia de bloqueo con subconsultas podría leer
    # asociaciones previas al commit del escritor por el que esperó.
    actual = Publicacion.objects.select_for_update().only('pk').filter(pk=publicacion_id).first()
    if actual is not None:
        actual = _candidatas().filter(pk=publicacion_id).first()
    if actual is None:
        return {'id': publicacion_id, 'omitida': 'eliminada_o_sin_cuerpo'}

    resultado, etiquetas = _proponer(actual)
    # El alta de artículos toma los bloqueos de etiquetas antes del catálogo temático.
    if etiquetas:
        guardar_etiquetas_propuestas(actual, etiquetas)
        resultado['etiquetado'] = 'creado'
    if resultado['categoria']:
        vincular_categoria_por_nombre(
            actual, resultado['categoria'], procedencia_analisis=procedencia(
                Metodo.REGLAS, VERSION_CLASIFICACION_LOCAL,
            ),
        )
        resultado['clasificacion'] = 'creada'
    return resultado
