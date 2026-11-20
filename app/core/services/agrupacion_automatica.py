"""Agrupación automática de duplicados editoriales inequívocos.

La regla es opt-in, opera por pares directos y deja trazabilidad de sistema,
sin suplantar revisores humanos ni modificar publicaciones originales.
"""

from datetime import date, datetime
from hashlib import sha256
from html import unescape
import unicodedata

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.utils.html import strip_tags

from core.models import (
    CandidatoDuplicadoEditorial, EventoRevisionEditorial, GrupoEditorial,
    MiembroGrupoEditorial, Publicacion,
)
from core.services.agrupacion_editorial import (
    VERSION_DETECTOR, _bloquear_publicaciones, _huella, seleccionar_representante,
)
from core.services.deteccion_sombra_editorial import _huella as _huella_candidato
from core.services.deteccion_sombra_editorial import _fila_detector
from core.services.duplicados_editoriales import detectar_candidatos, normalizar_fuente, normalizar_texto


VERSION_REGLA_AUTOMATICA = 'auto-editorial-exacto-v1'
LONGITUD_MINIMA_CUERPO = 300
MAX_CANDIDATOS_PREVISUALIZACION = 1000


def _cuerpo_equivalente(valor):
    """Normaliza sólo formato; conserva puntuación y palabras editoriales."""
    texto = strip_tags(unescape(str(valor or '')))
    texto = unicodedata.normalize('NFC', texto).casefold()
    return ' '.join(texto.split())


def _fecha_editorial(publicacion):
    fecha = publicacion.fecha_publicacion
    if isinstance(fecha, datetime):
        return fecha.date()
    if isinstance(fecha, date):
        return fecha
    return None


def _huella_publicacion_detector(publicacion):
    return _huella_candidato(_fila_detector({
        'pk': publicacion.pk,
        'fuente': publicacion.fuente,
        'titulo': publicacion.titulo,
        'url': publicacion.url,
        'fecha_publicacion': publicacion.fecha_publicacion,
        'contenido': publicacion.contenido,
        'contenido_completo': publicacion.contenido_completo,
    }))


def evaluar_elegibilidad(candidato, *, publicaciones_en_grupo=frozenset()):
    """Revalida un candidato contra los registros actuales, sin escribir."""
    publicaciones = (candidato.publicacion_a, candidato.publicacion_b)
    ids = tuple(publicacion.pk for publicacion in publicaciones)

    def no_elegible(motivo):
        return {'elegible': False, 'motivo': motivo, 'candidato_id': candidato.pk, 'publicacion_ids': ids}

    if candidato.estado != CandidatoDuplicadoEditorial.Estado.PENDIENTE:
        return no_elegible('CANDIDATO_NO_PENDIENTE')
    if candidato.automatizacion_bloqueada:
        return no_elegible('AUTOMATIZACION_BLOQUEADA')
    if candidato.clasificacion not in (
        CandidatoDuplicadoEditorial.Clasificacion.PROBABLE,
        CandidatoDuplicadoEditorial.Clasificacion.EXACTO,
    ):
        return no_elegible('CLASIFICACION_NO_ELEGIBLE')
    if candidato.version_detector != VERSION_DETECTOR:
        return no_elegible('VERSION_DETECTOR_DESACTUALIZADA')
    if set(ids) & set(publicaciones_en_grupo):
        return no_elegible('PUBLICACION_EN_GRUPO_VIGENTE')

    a, b = publicaciones
    huellas = [_huella_publicacion_detector(a), _huella_publicacion_detector(b)]
    huellas_evidencia = (candidato.evidencia or {}).get('huellas_publicacion')
    if (candidato.huella_a, candidato.huella_b) != tuple(huellas) or huellas_evidencia != huellas:
        return no_elegible('EVIDENCIA_DESACTUALIZADA')
    if (candidato.evidencia or {}).get('version_detector') != VERSION_DETECTOR:
        return no_elegible('VERSION_EVIDENCIA_DESACTUALIZADA')

    if not a.fuente or not b.fuente:
        return no_elegible('FUENTE_INVALIDA')
    fuente_normalizada = normalizar_fuente(a.fuente)
    fuente_b_normalizada = normalizar_fuente(b.fuente)
    if not fuente_normalizada or not fuente_b_normalizada:
        return no_elegible('FUENTE_INVALIDA')
    if fuente_normalizada != fuente_b_normalizada:
        return no_elegible('FUENTE_DISTINTA')
    if (candidato.fuente_normalizada != fuente_normalizada
            or (candidato.evidencia or {}).get('fuente_normalizada') != fuente_normalizada):
        return no_elegible('FUENTE_EVIDENCIA_DESACTUALIZADA')

    titulo_a, titulo_b = normalizar_texto(a.titulo), normalizar_texto(b.titulo)
    if not titulo_a or titulo_a != titulo_b:
        return no_elegible('TITULO_NO_EQUIVALENTE')
    fecha_a, fecha_b = _fecha_editorial(a), _fecha_editorial(b)
    if not fecha_a or not fecha_b:
        return no_elegible('FECHA_EDITORIAL_AUSENTE')
    if fecha_a != fecha_b:
        return no_elegible('FECHA_EDITORIAL_DISTINTA')
    if a.contenido_completo is not True or b.contenido_completo is not True:
        return no_elegible('CONTENIDO_INCOMPLETO')

    cuerpo_a, cuerpo_b = _cuerpo_equivalente(a.contenido), _cuerpo_equivalente(b.contenido)
    if min(len(cuerpo_a), len(cuerpo_b)) < LONGITUD_MINIMA_CUERPO:
        return no_elegible('CUERPO_INSUFICIENTE')
    if cuerpo_a != cuerpo_b:
        return no_elegible('CUERPO_NO_EQUIVALENTE')

    detectados = detectar_candidatos([_fila_detector({
        'pk': a.pk, 'fuente': a.fuente, 'titulo': a.titulo, 'url': a.url,
        'fecha_publicacion': a.fecha_publicacion, 'contenido': a.contenido,
        'contenido_completo': a.contenido_completo,
    }), _fila_detector({
        'pk': b.pk, 'fuente': b.fuente, 'titulo': b.titulo, 'url': b.url,
        'fecha_publicacion': b.fecha_publicacion, 'contenido': b.contenido,
        'contenido_completo': b.contenido_completo,
    })])
    directa = next((item for item in detectados if set(row['pk'] for row in item['publicaciones']) == set(ids)), None)
    if directa is None or directa['estado'] != 'DUPLICADO_CONFIRMADO':
        return no_elegible('DETECTOR_NO_CONFIRMA_PAREJA')

    cuerpo_hash = sha256(cuerpo_a.encode('utf-8')).hexdigest()
    return {
        'elegible': True,
        'motivo': 'MISMA_FUENTE_TITULO_FECHA_Y_CUERPO_EXACTOS',
        'candidato_id': candidato.pk,
        'publicacion_ids': ids,
        'fuente': a.fuente,
        'fecha_editorial': fecha_a.isoformat(),
        'version_detector': VERSION_DETECTOR,
        'version_regla': VERSION_REGLA_AUTOMATICA,
        'huellas_publicacion': huellas,
        'huella_cuerpo_equivalente': cuerpo_hash,
        'longitud_cuerpo_normalizado': len(cuerpo_a),
        'similitud_detector': {
            'titulo': directa['similitud_titulo'],
            'cuerpo': directa['similitud_contenido'],
            'estado': directa['estado'],
        },
        'criterios': [
            'misma fuente normalizada (incluye alias configurados del mismo medio)',
            'título normalizado idéntico',
            'fecha editorial idéntica; no se usa fecha de captura ni lastmod',
            f'ambos cuerpos completos y de al menos {LONGITUD_MINIMA_CUERPO} caracteres',
            'cuerpo idéntico tras normalizar HTML, Unicode, caja y espacios; se conserva puntuación',
            'huellas actuales iguales a la evidencia registrada',
            'confirmación directa del detector para el par, sin transitividad',
        ],
    }


def _cargar_candidatos(*, limite=MAX_CANDIDATOS_PREVISUALIZACION, fuente=''):
    if type(limite) is not int or not 1 <= limite <= MAX_CANDIDATOS_PREVISUALIZACION:
        raise ValueError('El límite debe estar entre 1 y 1000.')
    consulta = CandidatoDuplicadoEditorial.objects.select_related(
        'publicacion_a', 'publicacion_b',
    ).order_by('pk')
    if fuente:
        consulta = consulta.filter(fuente_normalizada=normalizar_fuente(fuente))
    return list(consulta[:limite])


def previsualizar_candidatos(*, limite=MAX_CANDIDATOS_PREVISUALIZACION, fuente=''):
    """Devuelve evaluación explicable; el llamador debe usar transacción READ ONLY."""
    candidatos = _cargar_candidatos(limite=limite, fuente=fuente)
    publicacion_ids = {pk for c in candidatos for pk in (c.publicacion_a_id, c.publicacion_b_id)}
    publicaciones_en_grupo = set(MiembroGrupoEditorial.objects.filter(
        publicacion_id__in=publicacion_ids, vigente=True,
    ).values_list('publicacion_id', flat=True)) if publicacion_ids else set()
    return [evaluar_elegibilidad(c, publicaciones_en_grupo=publicaciones_en_grupo) for c in candidatos]


def aplicar_candidato_automatico(candidato_id):
    """Agrupa un único par en una transacción, tras volver a validar evidencia."""
    if not getattr(settings, 'AGRUPACION_EDITORIAL_AUTOMATICA_HABILITADA', False):
        raise PermissionDenied('La agrupación editorial automática permanece deshabilitada.')

    referencias = CandidatoDuplicadoEditorial.objects.filter(pk=candidato_id).values_list(
        'publicacion_a_id', 'publicacion_b_id',
    ).first()
    if referencias is None:
        return {'creado': False, 'motivo': 'CANDIDATO_INEXISTENTE', 'candidato_id': candidato_id}

    with transaction.atomic():
        bloqueadas = _bloquear_publicaciones(referencias)
        if len(bloqueadas) != 2:
            return {'creado': False, 'motivo': 'PUBLICACION_INEXISTENTE', 'candidato_id': candidato_id}
        candidato = CandidatoDuplicadoEditorial.objects.select_for_update(of=('self',)).select_related(
            'publicacion_a', 'publicacion_b',
        ).get(pk=candidato_id)
        if (candidato.publicacion_a_id, candidato.publicacion_b_id) != tuple(referencias):
            return {'creado': False, 'motivo': 'PAR_PUBLICACIONES_CAMBIO', 'candidato_id': candidato.pk}
        ocupadas = set(MiembroGrupoEditorial.objects.filter(
            publicacion_id__in=referencias, vigente=True,
        ).values_list('publicacion_id', flat=True))
        evaluacion = evaluar_elegibilidad(candidato, publicaciones_en_grupo=ocupadas)
        if not evaluacion['elegible']:
            return {'creado': False, 'motivo': evaluacion['motivo'], 'candidato_id': candidato.pk}

        publicaciones = [bloqueadas[candidato.publicacion_a_id], bloqueadas[candidato.publicacion_b_id]]
        representante = seleccionar_representante(publicaciones)
        miembro = next(p for p in publicaciones if p.pk != representante.pk)
        ahora = timezone.now()
        criterio = {
            'origen': 'AUTOMATICA',
            'regla_version': VERSION_REGLA_AUTOMATICA,
            'detector_version': VERSION_DETECTOR,
            'candidato_id': candidato.pk,
            'representante_id': representante.pk,
            'criterios': evaluacion['criterios'],
        }
        motivo = f'Agrupación por regla automática {VERSION_REGLA_AUTOMATICA}; sin revisor humano.'
        grupo = GrupoEditorial.objects.create(
            representante=representante,
            estado=GrupoEditorial.Estado.ACTIVO,
            origen_decision=GrupoEditorial.OrigenDecision.AUTOMATICA,
            regla_automatica_version=VERSION_REGLA_AUTOMATICA,
            candidato_automatico=candidato,
            version_detector=VERSION_DETECTOR,
            criterio_representante=criterio,
            creado_por=None,
            aprobado_por=None,
            aprobado=ahora,
            motivo_aprobacion=motivo,
        )
        for publicacion, rol in (
            (representante, MiembroGrupoEditorial.Rol.REPRESENTANTE),
            (miembro, MiembroGrupoEditorial.Rol.MIEMBRO),
        ):
            MiembroGrupoEditorial.objects.create(
                grupo=grupo,
                publicacion=publicacion,
                rol=rol,
                decision=MiembroGrupoEditorial.Decision.APROBADO,
                evidencia={
                    'metodo_decision': 'AUTOMATICA',
                    'regla_version': VERSION_REGLA_AUTOMATICA,
                    'candidato_id': candidato.pk,
                    'huellas_publicacion': evaluacion['huellas_publicacion'],
                    'huella_cuerpo_equivalente': evaluacion['huella_cuerpo_equivalente'],
                    'detector': evaluacion['similitud_detector'],
                },
                huella_publicacion=_huella(publicacion),
                version_detector=VERSION_DETECTOR,
                metodo_decision=MiembroGrupoEditorial.MetodoDecision.AUTOMATICA,
                regla_automatica_version=VERSION_REGLA_AUTOMATICA,
                revisado=ahora,
                revisado_por=None,
                motivo_revision=motivo,
                vigente=True,
            )

        clave_evento = sha256(
            f'{VERSION_REGLA_AUTOMATICA}:{VERSION_DETECTOR}:{candidato.pk}'.encode('utf-8'),
        ).hexdigest()
        EventoRevisionEditorial.objects.create(
            grupo=grupo,
            miembro=None,
            actor=None,
            metodo_actor=EventoRevisionEditorial.MetodoActor.AUTOMATIZACION,
            regla_automatica_version=VERSION_REGLA_AUTOMATICA,
            clave_idempotencia=clave_evento,
            tipo=EventoRevisionEditorial.Tipo.AUTOAGRUPADO,
            motivo=motivo,
            evidencia={
                **evaluacion,
                'representante_id': representante.pk,
                'publicaciones_originales_preservadas': True,
                'revisor_humano': None,
            },
        )
        candidato.estado = CandidatoDuplicadoEditorial.Estado.EN_GRUPO
        candidato.motivo_estado = 'AGRUPACION_AUTOMATICA'
        candidato.save(update_fields=['estado', 'motivo_estado'])
        return {
            'creado': True,
            'motivo': evaluacion['motivo'],
            'candidato_id': candidato.pk,
            'grupo_id': grupo.pk,
            'representante_id': representante.pk,
            'publicacion_ids': list(evaluacion['publicacion_ids']),
            'version_regla': VERSION_REGLA_AUTOMATICA,
        }
