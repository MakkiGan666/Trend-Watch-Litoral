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
def registrar_candidatos_sombra(candidatos, *, version_detector=VERSION_DETECTOR,
                                reconciliar_anteriores=True, incluir_total=True):
    """Reevalúa pares contra la base y actualiza la cola sin transitividad.

    El insumo sólo aporta identificadores. Metadatos y cuerpos se vuelven a
    leer desde PostgreSQL para que un llamador no pueda falsificar evidencia.
    """
    if not isinstance(version_detector, str) or not version_detector.strip() or len(version_detector) > 40:
        raise ValueError('La versión del detector debe tener entre 1 y 40 caracteres.')
    if not isinstance(candidatos, (list, tuple)) or len(candidatos) > MAX_CANDIDATOS_POR_EJECUCION:
        raise ValueError('La ejecución excede el máximo de candidatos permitido.')
    if type(reconciliar_anteriores) is not bool:
        raise ValueError('reconciliar_anteriores debe ser booleano.')
    if type(incluir_total) is not bool:
        raise ValueError('incluir_total debe ser booleano.')

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

    # Reconcile pending rows on every explicit run, even when the detector no
    # longer emits their pair. This makes stale observations non-actionable.
    anteriores = list(CandidatoDuplicadoEditorial.objects.filter(estado__in=[
        CandidatoDuplicadoEditorial.Estado.PENDIENTE,
        CandidatoDuplicadoEditorial.Estado.EN_GRUPO,
    ]).values('publicacion_a_id', 'publicacion_b_id')) if reconciliar_anteriores else []
    pares_anteriores = {
        tuple(sorted((fila['publicacion_a_id'], fila['publicacion_b_id']))) for fila in anteriores
    }
    pares_todos = pares | pares_anteriores
    ids = {pk for par in pares_todos for pk in par}
    # All writers of editorial membership use this same publication-first,
    # ascending-PK lock order. Re-read after acquiring the locks.
    filas = {
        fila['pk']: fila for fila in Publicacion.objects.select_for_update().filter(pk__in=ids).order_by('pk').values(
            'pk', 'fuente', 'titulo', 'url', 'fecha_publicacion', 'contenido', 'contenido_completo',
        )
    }
    ids_entrada = {pk for par in pares for pk in par}
    if not ids_entrada.issubset(filas):
        raise ValueError('Uno o más candidatos refieren a publicaciones inexistentes.')
    pares_todos = {par for par in pares_todos if par[0] in filas and par[1] in filas}

    ocupadas = set(MiembroGrupoEditorial.objects.filter(
        publicacion_id__in=ids, vigente=True,
    ).values_list('publicacion_id', flat=True))

    filas_cola = list(CandidatoDuplicadoEditorial.objects.select_for_update().filter(
        Q(publicacion_a_id__in=ids) | Q(publicacion_b_id__in=ids),
    ).order_by('pk')) if ids else []
    filas_cola = [
        fila for fila in filas_cola
        if (fila.publicacion_a_id, fila.publicacion_b_id) in pares_todos
    ]
    por_par_version = {
        (fila.publicacion_a_id, fila.publicacion_b_id, fila.version_detector): fila for fila in filas_cola
    }
    por_par = {}
    for fila in filas_cola:
        por_par.setdefault((fila.publicacion_a_id, fila.publicacion_b_id), []).append(fila)
    guardados, obsoletos, en_grupo = 0, 0, 0
    omitidos = {'fuente_distinta': 0, 'grupo_vigente': 0, 'sin_evidencia_actual': 0, 'no_candidato': 0}
    ahora = timezone.now()
    for pk_a, pk_b in sorted(pares_todos):
        a, b = filas[pk_a], filas[pk_b]
        fuente = normalizar_fuente(a['fuente'])
        evaluacion = None
        if fuente and fuente == normalizar_fuente(b['fuente']) and pk_a not in ocupadas and pk_b not in ocupadas:
            evaluaciones = detectar_candidatos([_fila_detector(a), _fila_detector(b)])
            evaluacion = next((item for item in evaluaciones
                               if {publicacion['pk'] for publicacion in item['publicaciones']} == {pk_a, pk_b}), None)
        clasificacion = _CLASIFICACION_POR_ESTADO.get(evaluacion['estado']) if evaluacion else None
        if evaluacion and evaluacion['estado'] == 'DUPLICADO_CONFIRMADO' and evaluacion['misma_url_canonicalizada']:
            clasificacion = CandidatoDuplicadoEditorial.Clasificacion.EXACTO
        if evaluacion and clasificacion is None:
            omitidos['no_candidato'] += 1
        elif evaluacion is None:
            if pk_a in ocupadas or pk_b in ocupadas:
                omitidos['grupo_vigente'] += 1
            elif not fuente or fuente != normalizar_fuente(b['fuente']):
                omitidos['fuente_distinta'] += 1
            else:
                omitidos['sin_evidencia_actual'] += 1

        existentes = por_par.get((pk_a, pk_b), [])
        motivo_obsoleto = (
            'GRUPO_VIGENTE' if pk_a in ocupadas or pk_b in ocupadas
            else 'EVIDENCIA_INVALIDA' if evaluacion is None or clasificacion is None
            else ''
        )
        for existente in existentes:
            if motivo_obsoleto == 'GRUPO_VIGENTE':
                if (existente.estado != CandidatoDuplicadoEditorial.Estado.EN_GRUPO
                        or existente.motivo_estado != motivo_obsoleto):
                    existente.estado = CandidatoDuplicadoEditorial.Estado.EN_GRUPO
                    existente.motivo_estado = motivo_obsoleto
                    existente.save(update_fields=['estado', 'motivo_estado'])
                    en_grupo += 1
            elif existente.version_detector != version_detector:
                existente.estado = CandidatoDuplicadoEditorial.Estado.OBSOLETO
                existente.motivo_estado = 'VERSION_DESACTUALIZADA'
                existente.save(update_fields=['estado', 'motivo_estado'])
                obsoletos += 1
            elif motivo_obsoleto:
                nuevo_estado = (CandidatoDuplicadoEditorial.Estado.EN_GRUPO
                               if motivo_obsoleto == 'GRUPO_VIGENTE'
                               else CandidatoDuplicadoEditorial.Estado.OBSOLETO)
                if existente.estado != nuevo_estado or existente.motivo_estado != motivo_obsoleto:
                    existente.estado = nuevo_estado
                    existente.motivo_estado = motivo_obsoleto
                    existente.save(update_fields=['estado', 'motivo_estado'])
                    en_grupo += nuevo_estado == CandidatoDuplicadoEditorial.Estado.EN_GRUPO
                    obsoletos += nuevo_estado == CandidatoDuplicadoEditorial.Estado.OBSOLETO

        if evaluacion is None or clasificacion is None or pk_a in ocupadas or pk_b in ocupadas:
            continue
        evidencia = _evidencia(evaluacion, a, b, version_detector)
        huella_a, huella_b = _huella(a), _huella(b)
        clave = hashlib.sha256(f'{version_detector}:{pk_a}:{pk_b}'.encode('utf-8')).hexdigest()
        defaults = {
            'version_detector': version_detector,
            'clasificacion': clasificacion,
            'estado': CandidatoDuplicadoEditorial.Estado.PENDIENTE,
            'motivo_estado': '',
            'fuente_normalizada': fuente[:100],
            'huella_a': huella_a,
            'huella_b': huella_b,
            'evidencia': evidencia,
        }
        candidato_existente = por_par_version.get((pk_a, pk_b, version_detector))
        if candidato_existente:
            CandidatoDuplicadoEditorial.objects.filter(pk=candidato_existente.pk).update(
                **defaults, ultima_detectada=ahora, veces_detectado=F('veces_detectado') + 1,
            )
            guardados += 1
        else:
            CandidatoDuplicadoEditorial.objects.create(
                **defaults, publicacion_a_id=pk_a, publicacion_b_id=pk_b,
                clave_idempotencia=clave,
            )
            guardados += 1

    resultado = {
        'pares_recibidos': len(pares),
        'candidatos_registrados_o_actualizados': guardados,
        'candidatos_obsoletos': obsoletos,
        'candidatos_en_grupo_vigente': en_grupo,
        'omitidos': omitidos,
    }
    if incluir_total:
        resultado['total_cola'] = CandidatoDuplicadoEditorial.objects.count()
    return resultado
