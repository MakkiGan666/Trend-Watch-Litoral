"""Persistencia idempotente de candidatos editoriales en modo sombra.

Este servicio no crea grupos ni modifica publicaciones. Sólo acepta pares
recalculados desde Publicacion y excluye coberturas de medios diferentes.
"""

import hashlib
import json

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from core.models import CandidatoDuplicadoEditorial, MiembroGrupoEditorial, Publicacion
from core.services.duplicados_editoriales import (
    canonicalizar_url,
    detectar_candidatos,
    normalizar_fuente,
)
from core.services.agrupacion_editorial import VERSION_DETECTOR


MAX_CANDIDATOS_POR_EJECUCION = 5000
MAX_EVIDENCIA_BYTES = 8192

_CLASIFICACION_POR_ESTADO = {
    'DUPLICADO_CONFIRMADO': CandidatoDuplicadoEditorial.Clasificacion.PROBABLE,
    'DUPLICADO_PROBABLE': CandidatoDuplicadoEditorial.Clasificacion.PROBABLE,
    'DATOS_INSUFICIENTES': CandidatoDuplicadoEditorial.Clasificacion.AMBIGUO,
    'TITULO_REPETIDO_NO_CONFIRMADO': CandidatoDuplicadoEditorial.Clasificacion.AMBIGUO,
}


def _huella(fila):
    campos = {
        'fuente': fila['fuente'],
        'titulo': fila['titulo'],
        'url': fila['url'],
        'fecha_publicacion': fila['fecha_publicacion'].isoformat() if fila['fecha_publicacion'] else None,
        'contenido': fila['contenido'],
        'contenido_completo': fila['contenido_completo'],
    }
    serializado = json.dumps(campos, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(serializado.encode('utf-8')).hexdigest()


def _evidencia(candidato, a, b, version_detector):
    publicaciones = candidato['publicaciones']
    evidencia = {
        'estado_detector': candidato['estado'],
        'razon': candidato['razon'],
        'similitud_titulo': candidato['similitud_titulo'],
        'similitud_contenido': candidato['similitud_contenido'],
        'dias_entre_fechas_editoriales': candidato['dias_entre_fechas_editoriales'],
        'misma_url_canonicalizada': candidato['misma_url_canonicalizada'],
        'fechas_editoriales': [
            fila['fecha_publicacion'].isoformat() if fila['fecha_publicacion'] else None
            for fila in (a, b)
        ],
        'urls_canonicalizadas_sha256': [
            hashlib.sha256(canonicalizar_url(fila['url']).encode('utf-8')).hexdigest()
            for fila in (a, b)
        ],
        'huellas_publicacion': [_huella(a), _huella(b)],
        'fuente_normalizada': normalizar_fuente(publicaciones[0]['fuente_original']),
        'version_detector': version_detector,
    }
    serializado = json.dumps(evidencia, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    if len(serializado.encode('utf-8')) > MAX_EVIDENCIA_BYTES:
        raise ValueError('La evidencia del candidato supera el límite permitido.')
    return evidencia


def _fila_detector(fila):
    return {
        'pk': fila['pk'],
        'fuente': fila['fuente'],
        'titulo': fila['titulo'],
        'url': fila['url'],
        'fecha_publicacion': fila['fecha_publicacion'],
        'contenido': fila['contenido'],
        'contenido_completo': fila['contenido_completo'],
    }


@transaction.atomic
def registrar_candidatos_sombra(candidatos, *, version_detector=VERSION_DETECTOR):
    """Reevalúa pares contra la base y actualiza la cola sin transitividad.

    El insumo sólo aporta identificadores. Metadatos y cuerpos se vuelven a
    leer desde PostgreSQL para que un llamador no pueda falsificar evidencia.
    """
    if not isinstance(version_detector, str) or not version_detector.strip() or len(version_detector) > 40:
        raise ValueError('La versión del detector debe tener entre 1 y 40 caracteres.')
    if not isinstance(candidatos, (list, tuple)) or len(candidatos) > MAX_CANDIDATOS_POR_EJECUCION:
        raise ValueError('La ejecución excede el máximo de candidatos permitido.')

    pares = set()
    for candidato in candidatos:
        try:
            publicaciones = candidato['publicaciones']
            ids = [int(publicacion['pk']) for publicacion in publicaciones]
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError('Cada candidato debe identificar dos publicaciones existentes.') from error
        if len(ids) != 2 or ids[0] == ids[1] or min(ids) < 1:
            raise ValueError('Cada candidato debe contener dos IDs positivos y distintos.')
        pares.add(tuple(sorted(ids)))

    ids = {pk for par in pares for pk in par}
    filas = {
        fila['pk']: fila for fila in Publicacion.objects.filter(pk__in=ids).values(
            'pk', 'fuente', 'titulo', 'url', 'fecha_publicacion', 'contenido', 'contenido_completo',
        )
    }
    if len(filas) != len(ids):
        raise ValueError('Uno o más candidatos refieren a publicaciones inexistentes.')

    ocupadas = set(MiembroGrupoEditorial.objects.filter(
        Q(publicacion_id__in=ids), vigente=True,
    ).values_list('publicacion_id', flat=True))

    guardados, omitidos = 0, {'fuente_distinta': 0, 'grupo_vigente': 0, 'sin_evidencia_actual': 0, 'no_candidato': 0}
    for pk_a, pk_b in sorted(pares):
        a, b = filas[pk_a], filas[pk_b]
        fuente = normalizar_fuente(a['fuente'])
        if not fuente or fuente != normalizar_fuente(b['fuente']):
            omitidos['fuente_distinta'] += 1
            continue
        if pk_a in ocupadas or pk_b in ocupadas:
            omitidos['grupo_vigente'] += 1
            continue

        evaluaciones = detectar_candidatos([_fila_detector(a), _fila_detector(b)])
        evaluacion = next((item for item in evaluaciones
                           if {publicacion['pk'] for publicacion in item['publicaciones']} == {pk_a, pk_b}), None)
        if evaluacion is None:
            omitidos['sin_evidencia_actual'] += 1
            continue
        clasificacion = _CLASIFICACION_POR_ESTADO.get(evaluacion['estado'])
        if evaluacion['estado'] == 'DUPLICADO_CONFIRMADO' and evaluacion['misma_url_canonicalizada']:
            clasificacion = CandidatoDuplicadoEditorial.Clasificacion.EXACTO
        if clasificacion is None:
            # Incluye coberturas entre medios y títulos parecidos con cuerpos distintos.
            omitidos['no_candidato'] += 1
            continue

        evidencia = _evidencia(evaluacion, a, b, version_detector)
        clave = hashlib.sha256(
            f'{version_detector}:{pk_a}:{pk_b}'.encode('utf-8')
        ).hexdigest()
        defaults = {
            'version_detector': version_detector,
            'clasificacion': clasificacion,
            'fuente_normalizada': fuente[:100],
            'huella_a': _huella(a),
            'huella_b': _huella(b),
            'evidencia': evidencia,
        }
        _, creado = CandidatoDuplicadoEditorial.objects.get_or_create(
            clave_idempotencia=clave,
            defaults={**defaults, 'publicacion_a_id': pk_a, 'publicacion_b_id': pk_b},
        )
        if creado:
            guardados += 1
        else:
            CandidatoDuplicadoEditorial.objects.filter(clave_idempotencia=clave).update(
                ultima_detectada=timezone.now(),
                veces_detectado=F('veces_detectado') + 1,
                clasificacion=clasificacion,
                fuente_normalizada=fuente[:100],
                huella_a=defaults['huella_a'],
                huella_b=defaults['huella_b'],
                evidencia=evidencia,
            )
            guardados += 1

    return {
        'pares_recibidos': len(pares),
        'candidatos_registrados_o_actualizados': guardados,
        'omitidos': omitidos,
        'total_cola': CandidatoDuplicadoEditorial.objects.count(),
    }
