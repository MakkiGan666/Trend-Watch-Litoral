"""Operaciones transaccionales de revisión editorial.

Los candidatos se comparan directamente con la representante congelada del
grupo. Este módulo no modifica Publicacion ni sus relaciones.
"""

import hashlib
import json
from datetime import timezone as datetime_timezone

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.utils import timezone

from core.models import (
    EventoRevisionEditorial, GrupoEditorial, MiembroGrupoEditorial, Publicacion,
)
from core.services.duplicados_editoriales import detectar_candidatos, normalizar_fuente


VERSION_DETECTOR = 'editorial-v1'
MAX_MIEMBROS = 20
_PERM_REVISAR = 'core.revisar_candidatos_editoriales'
_PERM_APROBAR = 'core.aprobar_agrupacion_editorial'
_PERM_REVOCAR = 'core.revocar_agrupacion_editorial'


def _exigir_permiso(actor, permiso):
    if not getattr(actor, 'is_authenticated', False) or not actor.has_perm(permiso):
        raise PermissionDenied('No tiene permiso para esta operación editorial.')


def _motivo(motivo):
    valor = str(motivo or '').strip()
    if not valor or len(valor) > 500:
        raise ValidationError('El motivo es obligatorio y no puede superar 500 caracteres.')
    return valor


def seleccionar_representante(publicaciones):
    """Elige de forma determinista sin hacer solicitudes externas."""
    filas = list(publicaciones)
    if not filas:
        raise ValidationError('Se requiere al menos una publicación.')
    validar_url = URLValidator(schemes=('http', 'https'))

    def puntaje(publicacion):
        cuerpo = publicacion.contenido_completo is True and bool((publicacion.contenido or '').strip())
        try:
            validar_url(publicacion.url or '')
            url_valida = True
        except ValidationError:
            url_valida = False
        metadata = bool(
            (publicacion.titulo or '').strip()
            and url_valida
            and (publicacion.fuente or '').strip()
            and publicacion.fecha_publicacion is not None
        )
        imagen = 2 if bool(getattr(publicacion.imagen_archivo, 'name', '')) else (
            1 if (publicacion.imagen_url or '').strip() else 0
        )
        fecha = float('-inf')
        if publicacion.fecha_publicacion:
            publicada = publicacion.fecha_publicacion
            if timezone.is_naive(publicada):
                publicada = timezone.make_aware(publicada, timezone.get_default_timezone())
            fecha = publicada.astimezone(datetime_timezone.utc).timestamp()
        return (bool(cuerpo), metadata, imagen, fecha, -publicacion.pk)

    return max(filas, key=puntaje)


def _fila(publicacion):
    return {
        'pk': publicacion.pk,
        'fuente': publicacion.fuente,
        'titulo': publicacion.titulo,
        'url': publicacion.url,
        'fecha_publicacion': publicacion.fecha_publicacion.isoformat() if publicacion.fecha_publicacion else None,
        'contenido_completo': publicacion.contenido_completo,
        'contenido': publicacion.contenido,
        'imagen_url': publicacion.imagen_url,
        'imagen_archivo': getattr(publicacion.imagen_archivo, 'name', ''),
    }


def _huella(publicacion):
    serializado = json.dumps(_fila(publicacion), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(serializado.encode('utf-8')).hexdigest()


def _evaluar_directamente(representante, miembro):
    if representante.pk == miembro.pk:
        return {'estado': 'REPRESENTANTE'}
    fuente_representante = normalizar_fuente(representante.fuente)
    if not fuente_representante or fuente_representante != normalizar_fuente(miembro.fuente):
        raise ValidationError('No se pueden agrupar publicaciones de medios distintos.')
    pares = detectar_candidatos([_fila(representante), _fila(miembro)])
    evaluacion = next((p for p in pares if p['publicaciones'][0]['pk'] != p['publicaciones'][1]['pk']), None)
    if evaluacion is None or evaluacion['estado'] != 'DUPLICADO_CONFIRMADO':
        raise ValidationError('La evidencia directa contra la representante no confirma la identidad editorial.')
    return evaluacion


@transaction.atomic
def crear_grupo(*, actor, publicacion_ids, representante_id=None, motivo, version_detector=VERSION_DETECTOR):
    _exigir_permiso(actor, _PERM_REVISAR)
    razon = _motivo(motivo)
    try:
        ids = [int(pk) for pk in publicacion_ids]
        representante_id = int(representante_id) if representante_id is not None else None
    except (TypeError, ValueError) as error:
        raise ValidationError('Los IDs de publicación deben ser enteros.') from error
    if not isinstance(version_detector, str) or len(version_detector) > 40:
        raise ValidationError('La versión del detector debe ser texto de hasta 40 caracteres.')
    if len(ids) < 2 or len(ids) > MAX_MIEMBROS or len(set(ids)) != len(ids):
        raise ValidationError(f'Indique entre 2 y {MAX_MIEMBROS} publicaciones distintas.')
    if representante_id is not None and representante_id not in ids:
        raise ValidationError('La representante debe formar parte de las publicaciones seleccionadas.')

    filas = list(Publicacion.objects.select_for_update().filter(pk__in=ids).order_by('pk'))
    if len(filas) != len(ids):
        raise ValidationError('Una o más publicaciones no existen.')
    representante = (
        next((fila for fila in filas if fila.pk == representante_id), None)
        if representante_id is not None else seleccionar_representante(filas)
    )
    otros = [fila for fila in filas if fila.pk != representante.pk]
    fuente_key = normalizar_fuente(representante.fuente)
    if not fuente_key or any(normalizar_fuente(fila.fuente) != fuente_key for fila in filas):
        raise ValidationError('No se pueden agrupar publicaciones de medios distintos.')
    evidencia = {str(fila.pk): _evaluar_directamente(representante, fila) for fila in otros}
    if MiembroGrupoEditorial.objects.filter(publicacion_id__in=ids, vigente=True).exists():
        raise ValidationError('Una publicación seleccionada ya pertenece a un grupo vigente.')

    grupo = GrupoEditorial.objects.create(
        representante=representante, creado_por=actor, version_detector=version_detector,
        criterio_representante={
            'regla': 'cuerpo, metadatos, imagen, fecha editorial descendente, id ascendente',
            'seleccionada_por': 'usuario' if representante_id is not None else 'regla_determinista',
            'representante_id': representante.pk,
        },
    )
    for fila in filas:
        rol = (MiembroGrupoEditorial.Rol.REPRESENTANTE if fila.pk == representante.pk
               else MiembroGrupoEditorial.Rol.MIEMBRO)
        MiembroGrupoEditorial.objects.create(
            grupo=grupo, publicacion=fila, rol=rol,
            evidencia={'estado': 'REPRESENTANTE'} if rol == MiembroGrupoEditorial.Rol.REPRESENTANTE
            else evidencia[str(fila.pk)],
            huella_publicacion=_huella(fila), version_detector=version_detector,
        )
    EventoRevisionEditorial.objects.create(
        grupo=grupo, actor=actor, tipo=EventoRevisionEditorial.Tipo.CREADO,
        motivo=razon, evidencia={
            'version_detector': version_detector,
            'representante_id': representante.pk,
            'miembros_directos': evidencia,
        },
    )
    return grupo

@transaction.atomic
def decidir_miembro(*, actor, miembro_id, decision, motivo):
    _exigir_permiso(actor, _PERM_REVISAR)
    razon = _motivo(motivo)
    if decision not in (MiembroGrupoEditorial.Decision.APROBADO, MiembroGrupoEditorial.Decision.RECHAZADO):
        raise ValidationError('Decisión no válida.')
    grupo_id = MiembroGrupoEditorial.objects.only('grupo_id').get(pk=miembro_id).grupo_id
    grupo = GrupoEditorial.objects.select_for_update().get(pk=grupo_id)
    miembro = MiembroGrupoEditorial.objects.select_for_update(of=('self',)).select_related(
        'publicacion',
    ).get(pk=miembro_id, grupo_id=grupo.pk)
    if grupo.estado != GrupoEditorial.Estado.BORRADOR or miembro.decision != MiembroGrupoEditorial.Decision.PENDIENTE:
        raise ValidationError('Sólo se pueden decidir miembros pendientes de un grupo en revisión.')
    publicacion = Publicacion.objects.select_for_update().get(pk=miembro.publicacion_id)
    representante = Publicacion.objects.get(pk=grupo.representante_id)
    evidencia = {'estado': 'REPRESENTANTE'} if miembro.rol == MiembroGrupoEditorial.Rol.REPRESENTANTE else _evaluar_directamente(
        representante, publicacion,
    )
    miembro.decision = decision
    miembro.evidencia = evidencia
    miembro.huella_publicacion = _huella(publicacion)
    miembro.revisado_por = actor
    miembro.revisado = timezone.now()
    miembro.motivo_revision = razon
    miembro.save(update_fields=[
        'decision', 'evidencia', 'huella_publicacion', 'revisado_por', 'revisado', 'motivo_revision',
    ])
    EventoRevisionEditorial.objects.create(
        grupo=grupo, miembro=miembro, actor=actor,
        tipo=(EventoRevisionEditorial.Tipo.APROBADO if decision == MiembroGrupoEditorial.Decision.APROBADO
              else EventoRevisionEditorial.Tipo.RECHAZADO),
        motivo=razon, evidencia=evidencia,
    )
    return miembro


@transaction.atomic
def activar_grupo(*, actor, grupo_id, motivo, representante_id=None):
    _exigir_permiso(actor, _PERM_APROBAR)
    razon = _motivo(motivo)
    grupo = GrupoEditorial.objects.select_for_update().get(pk=grupo_id)
    if grupo.estado != GrupoEditorial.Estado.BORRADOR:
        raise ValidationError('Sólo se puede activar un grupo en revisión.')
    miembros = list(grupo.miembros.select_for_update(of=('self',)).order_by('publicacion_id'))
    # Bloquear todas las publicaciones en orden estable y volver a comprobar las huellas.
    publicacion_ids = [miembro.publicacion_id for miembro in miembros]
    bloqueadas = {p.pk: p for p in Publicacion.objects.select_for_update().filter(pk__in=publicacion_ids).order_by('pk')}
    if representante_id is not None:
        try:
            representante_id = int(representante_id)
        except (TypeError, ValueError) as error:
            raise ValidationError('La representante debe ser una publicación del grupo.') from error
        if representante_id not in bloqueadas:
            raise ValidationError('La representante seleccionada no pertenece al grupo.')
        if representante_id != grupo.representante_id:
            representante_nueva = bloqueadas[representante_id]
            fuente_nueva = normalizar_fuente(representante_nueva.fuente)
            if not fuente_nueva or any(normalizar_fuente(p.fuente) != fuente_nueva
                   for p in bloqueadas.values()):
                raise ValidationError('No se pueden agrupar publicaciones de medios distintos.')
            evidencia_nueva = {}
            for publicacion_id, publicacion in bloqueadas.items():
                if publicacion_id != representante_id:
                    evidencia_nueva[publicacion_id] = _evaluar_directamente(representante_nueva, publicacion)
            por_publicacion = {miembro.publicacion_id: miembro for miembro in miembros}
            representante_anterior = por_publicacion[grupo.representante_id]
            representante_anterior.rol = MiembroGrupoEditorial.Rol.MIEMBRO
            representante_anterior.save(update_fields=['rol'])
            miembro_nuevo = por_publicacion[representante_id]
            miembro_nuevo.rol = MiembroGrupoEditorial.Rol.REPRESENTANTE
            for miembro in miembros:
                miembro.decision = MiembroGrupoEditorial.Decision.PENDIENTE
                miembro.revisado_por = None
                miembro.revisado = None
                miembro.motivo_revision = ''
                miembro.vigente = False
                miembro.huella_publicacion = _huella(bloqueadas[miembro.publicacion_id])
                miembro.evidencia = (
                    {'estado': 'REPRESENTANTE'} if miembro.publicacion_id == representante_id
                    else evidencia_nueva[miembro.publicacion_id]
                )
                campos = [
                    'decision', 'revisado_por', 'revisado', 'motivo_revision',
                    'vigente', 'huella_publicacion', 'evidencia',
                ]
                if miembro.pk == miembro_nuevo.pk:
                    campos.append('rol')
                miembro.save(update_fields=campos)
            grupo.representante = representante_nueva
            grupo.criterio_representante = {
                **(grupo.criterio_representante or {}),
                'seleccionada_por': 'aprobador',
                'representante_id': representante_id,
            }
            grupo.save(update_fields=['representante', 'criterio_representante'])
            EventoRevisionEditorial.objects.create(
                grupo=grupo, actor=actor, tipo=EventoRevisionEditorial.Tipo.REPRESENTANTE,
                motivo=razon, evidencia={
                    'representante_anterior_id': representante_anterior.publicacion_id,
                    'representante_seleccionada_id': representante_id,
                    'miembros_reevaluados_directamente': evidencia_nueva,
                    'revisiones_individuales_reabiertas': True,
                },
            )
            return {'grupo': grupo, 'requiere_revision': True}
    if any(m.decision == MiembroGrupoEditorial.Decision.PENDIENTE for m in miembros):
        raise ValidationError('Cada integrante debe recibir una decisión individual antes de activar.')
    aprobados = [m for m in miembros if m.decision == MiembroGrupoEditorial.Decision.APROBADO]
    representante_miembro = next((m for m in miembros if m.rol == MiembroGrupoEditorial.Rol.REPRESENTANTE), None)
    if (not representante_miembro or representante_miembro not in aprobados
            or representante_miembro.publicacion_id != grupo.representante_id):
        raise ValidationError('La representante también requiere aprobación explícita.')
    secundarios = [m for m in aprobados if m.rol == MiembroGrupoEditorial.Rol.MIEMBRO]
    if not secundarios:
        raise ValidationError('Se requiere al menos un miembro aprobado además de la representante.')
    for miembro in aprobados:
        publicacion = bloqueadas[miembro.publicacion_id]
        if _huella(publicacion) != miembro.huella_publicacion:
            raise ValidationError('Una publicación cambió desde su revisión; requiere nueva revisión.')
        if miembro.rol == MiembroGrupoEditorial.Rol.MIEMBRO:
            _evaluar_directamente(bloqueadas[grupo.representante_id], publicacion)
    if MiembroGrupoEditorial.objects.filter(publicacion_id__in=publicacion_ids, vigente=True).exists():
        raise ValidationError('Una publicación aprobada ya está asociada a otro grupo vigente.')
    ahora = timezone.now()
    for miembro in aprobados:
        miembro.vigente = True
        miembro.save(update_fields=['vigente'])
    grupo.estado = GrupoEditorial.Estado.ACTIVO
    grupo.aprobado_por = actor
    grupo.aprobado = ahora
    grupo.motivo_aprobacion = razon
    grupo.save(update_fields=['estado', 'aprobado_por', 'aprobado', 'motivo_aprobacion'])
    EventoRevisionEditorial.objects.create(
        grupo=grupo, actor=actor, tipo=EventoRevisionEditorial.Tipo.ACTIVADO,
        motivo=razon, evidencia={'publicaciones_vigentes': [m.publicacion_id for m in aprobados]},
    )
    return {'grupo': grupo, 'requiere_revision': False}


@transaction.atomic
def revocar_grupo(*, actor, grupo_id, motivo):
    _exigir_permiso(actor, _PERM_REVOCAR)
    razon = _motivo(motivo)
    grupo = GrupoEditorial.objects.select_for_update().get(pk=grupo_id)
    if grupo.estado != GrupoEditorial.Estado.ACTIVO:
        raise ValidationError('Sólo se pueden revocar grupos activos.')
    miembros = list(grupo.miembros.select_for_update(of=('self',)).filter(vigente=True).order_by('publicacion_id'))
    for miembro in miembros:
        miembro.vigente = False
        miembro.save(update_fields=['vigente'])
    grupo.estado = GrupoEditorial.Estado.REVOCADO
    grupo.revocado_por = actor
    grupo.revocado = timezone.now()
    grupo.motivo_revocacion = razon
    grupo.save(update_fields=['estado', 'revocado_por', 'revocado', 'motivo_revocacion'])
    EventoRevisionEditorial.objects.create(
        grupo=grupo, actor=actor, tipo=EventoRevisionEditorial.Tipo.REVOCADO,
        motivo=razon, evidencia={'membresias_liberadas': [m.publicacion_id for m in miembros]},
    )
    return grupo
