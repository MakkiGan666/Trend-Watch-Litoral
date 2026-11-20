"""Detección editorial incremental y acotada para publicaciones multifuente."""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.models import Publicacion, TrabajoDeteccionSombraEditorial
from core.services.deteccion_sombra_editorial import registrar_candidatos_sombra
from core.services.duplicados_editoriales import detectar_candidatos


MAX_TRABAJOS_POR_CICLO = 50
MAX_COMPARABLES_POR_PUBLICACION = 250
MAX_INTENTOS = 3
VENTANA_EDITORIAL = timedelta(days=2)


def _fila(publicacion):
    return {
        'pk': publicacion['pk'],
        'fuente': publicacion['fuente'],
        'titulo': publicacion['titulo'],
        'url': publicacion['url'],
        'fecha_publicacion': publicacion['fecha_publicacion'],
        'contenido': publicacion['contenido'],
        'contenido_completo': publicacion['contenido_completo'],
    }


def _candidatos_para(publicacion):
    """Compara sólo misma fuente/ventana editorial y devuelve pares directos."""
    if not publicacion['fecha_publicacion']:
        return [], False
    fecha = publicacion['fecha_publicacion']
    consultas = Publicacion.objects.filter(
        fuente=publicacion['fuente'],
        fecha_publicacion__range=(fecha - VENTANA_EDITORIAL, fecha + VENTANA_EDITORIAL),
    ).exclude(pk=publicacion['pk']).order_by('pk')[:MAX_COMPARABLES_POR_PUBLICACION + 1]
    comparables = list(consultas.values(
        'pk', 'fuente', 'titulo', 'url', 'fecha_publicacion', 'contenido', 'contenido_completo',
    ))
    if len(comparables) > MAX_COMPARABLES_POR_PUBLICACION:
        return [], True
    filas = [_fila(publicacion), *(_fila(fila) for fila in comparables)]
    candidatos = detectar_candidatos(filas)
    id_nuevo = publicacion['pk']
    directos = [candidato for candidato in candidatos
                if any(miembro['pk'] == id_nuevo for miembro in candidato['publicaciones'])]
    return directos, False


def _procesar_uno(publicacion_id):
    with transaction.atomic():
        trabajo = (TrabajoDeteccionSombraEditorial.objects.select_for_update(skip_locked=True)
                   .filter(publicacion_id=publicacion_id,
                           estado=TrabajoDeteccionSombraEditorial.Estado.PENDIENTE).first())
        if trabajo is None:
            return None
        publicacion = Publicacion.objects.filter(pk=publicacion_id).values(
            'pk', 'fuente', 'titulo', 'url', 'fecha_publicacion', 'contenido', 'contenido_completo',
        ).first()
        if publicacion is None:
            # La FK CASCADE normalmente elimina también este outbox. Si una
            # eliminación concurrente ganó la carrera, no hay trabajo que guardar.
            return {'estado': 'OMITIDO', 'publicacion_id': publicacion_id}
        candidatos, exceso = _candidatos_para(publicacion)
        if exceso:
            trabajo.estado = TrabajoDeteccionSombraEditorial.Estado.REVISION_MANUAL
            trabajo.codigo_error = 'VENTANA_COMPARACION_EXCEDIDA'
            trabajo.save(update_fields=('estado', 'codigo_error', 'actualizado'))
            return {'estado': 'REVISION_MANUAL', 'publicacion_id': publicacion_id,
                    'codigo': trabajo.codigo_error}
        resultado = registrar_candidatos_sombra(
            candidatos, reconciliar_anteriores=False, incluir_total=False,
        ) if candidatos else {'candidatos_registrados_o_actualizados': 0}
        trabajo.estado = TrabajoDeteccionSombraEditorial.Estado.COMPLETADO
        trabajo.candidatos_registrados = min(
            resultado['candidatos_registrados_o_actualizados'], 32767,
        )
        trabajo.codigo_error = ''
        trabajo.completado = timezone.now()
        trabajo.save(update_fields=(
            'estado', 'candidatos_registrados', 'codigo_error', 'completado', 'actualizado',
        ))
        return {'estado': 'COMPLETADO', 'publicacion_id': publicacion_id,
                'candidatos': trabajo.candidatos_registrados}


def _registrar_fallo(publicacion_id, error):
    with transaction.atomic():
        trabajo = (TrabajoDeteccionSombraEditorial.objects.select_for_update()
                   .filter(publicacion_id=publicacion_id,
                           estado=TrabajoDeteccionSombraEditorial.Estado.PENDIENTE).first())
        if trabajo is None:
            return
        trabajo.intentos += 1
        # No guardar el texto de la excepción, que puede incluir detalles
        # variables; sólo una clase de error acotada y auditable.
        trabajo.codigo_error = type(error).__name__[:48]
        if trabajo.intentos >= MAX_INTENTOS:
            trabajo.estado = TrabajoDeteccionSombraEditorial.Estado.REVISION_MANUAL
        trabajo.save(update_fields=('intentos', 'codigo_error', 'estado', 'actualizado'))


def procesar_cola_incremental(*, limite=MAX_TRABAJOS_POR_CICLO):
    """Consume una cantidad acotada de outbox rows; jamás agrupa ni audita el histórico."""
    if type(limite) is not int or not 1 <= limite <= MAX_TRABAJOS_POR_CICLO:
        raise ValueError(f'limite debe estar entre 1 y {MAX_TRABAJOS_POR_CICLO}.')
    if not getattr(settings, 'DETECCION_EDITORIAL_SOMBRA_MULTIFUENTE_HABILITADA', False):
        return {'habilitada': False, 'procesados': 0, 'candidatos': 0, 'revision_manual': 0}

    ids = list(TrabajoDeteccionSombraEditorial.objects.filter(
        estado=TrabajoDeteccionSombraEditorial.Estado.PENDIENTE,
    ).order_by('creado', 'publicacion_id').values_list('publicacion_id', flat=True)[:limite])
    salida = []
    for publicacion_id in ids:
        try:
            resultado = _procesar_uno(publicacion_id)
            if resultado is not None:
                salida.append(resultado)
        except Exception as error:
            _registrar_fallo(publicacion_id, error)
            salida.append({'estado': 'REINTENTABLE', 'publicacion_id': publicacion_id,
                           'error': type(error).__name__})
    return {
        'habilitada': True,
        'procesados': sum(r['estado'] == 'COMPLETADO' for r in salida),
        'candidatos': sum(r.get('candidatos', 0) for r in salida),
        'revision_manual': sum(r['estado'] == 'REVISION_MANUAL' for r in salida),
        'reintentos': sum(r['estado'] == 'REINTENTABLE' for r in salida),
        'resultados': salida,
    }
