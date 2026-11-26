"""Selección explícita, aprobación y aplicación atómica de enriquecimiento."""

import hashlib
import json
from collections import defaultdict
from datetime import datetime
from hmac import compare_digest

from django.core.serializers.json import DjangoJSONEncoder
from django.db import OperationalError, transaction

from core.localidades import normalizar_nombre
from core.models import AplicacionLoteEnriquecimientoLocal, Publicacion, PublicacionEtiqueta, PublicacionTema
from core.services.clasificacion import vincular_categoria_por_nombre
from core.services.enriquecimiento_local import proponer
from core.services.etiquetas import VERSION_ETIQUETAS, asegurar_catalogo_etiquetas, guardar_etiquetas_propuestas
from core.services.procedencia_analitica import Metodo, procedencia
from core.services.temas_locales import VERSION_CLASIFICACION_LOCAL


class LoteInvalido(ValueError):
    pass


class _CodificadorHuella(DjangoJSONEncoder):
    def default(self, valor):
        if isinstance(valor, datetime):
            return valor.isoformat(timespec='microseconds')
        return super().default(valor)


def _huella(datos):
    canonico = json.dumps(datos, cls=_CodificadorHuella, sort_keys=True, ensure_ascii=False,
                          separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(canonico.encode('utf-8')).hexdigest()


def _ids_validos(ids, excluidos):
    for lista in (ids, excluidos):
        if (not isinstance(lista, list) or len(lista) > 1000
                or any(type(pk) is not int or not 1 <= pk <= 9223372036854775807 for pk in lista)
                or len(set(lista)) != len(lista)):
            raise LoteInvalido('Se requieren IDs positivos, únicos y un máximo de 1000 por lista.')
    if not ids or set(ids).intersection(excluidos):
        raise LoteInvalido('La selección está vacía o contiene IDs expresamente excluidos.')


def _versiones():
    return {'clasificacion': VERSION_CLASIFICACION_LOCAL, 'etiquetas': VERSION_ETIQUETAS}


def _asociaciones(modelo, campo_publicacion, ids, bloquear):
    filas = modelo.objects.filter(**{f'{campo_publicacion}__in': ids}).order_by(campo_publicacion, 'pk')
    if bloquear:
        # Un editor que ya tiene el vínculo podría estar esperando su FK a la
        # publicación. No esperar acá evita invertir su orden de bloqueo.
        filas = filas.select_for_update(nowait=True)
    try:
        valores = list(filas.values())
    except OperationalError as error:
        causa = error.__cause__
        codigo = getattr(causa, 'sqlstate', None) or getattr(causa, 'pgcode', None)
        if codigo == '55P03':
            raise LoteInvalido('Hay una asociación bloqueada por otro escritor.') from error
        raise
    agrupadas = defaultdict(list)
    for fila in valores:
        agrupadas[fila[campo_publicacion]].append(fila)
    return agrupadas


def _leer_estado(ids, *, bloquear=False):
    candidatas = Publicacion.objects.filter(pk__in=ids).order_by('pk').only(
        'titulo', 'contenido', 'contenido_completo',
    )
    if bloquear:
        candidatas = candidatas.select_for_update()
    publicaciones = list(candidatas)
    faltantes = sorted(set(ids) - {p.pk for p in publicaciones})
    if faltantes:
        raise LoteInvalido(f'Publicaciones inexistentes: {faltantes}.')
    for publicacion in publicaciones:
        if not publicacion.tiene_cuerpo_completo:
            raise LoteInvalido(f'Publicación {publicacion.pk} sin cuerpo completo.')
        if normalizar_nombre(publicacion.titulo) == 'prueba de publicacion':
            raise LoteInvalido(f'La publicación {publicacion.pk} es una publicación de prueba.')

    temas = _asociaciones(PublicacionTema, 'id_publicacion_api_id', ids, bloquear)
    etiquetas = _asociaciones(PublicacionEtiqueta, 'publicacion_id', ids, bloquear)
    return [(p, temas[p.pk], etiquetas[p.pk]) for p in publicaciones]


def _estado_publicacion(publicacion, temas, etiquetas):
    return {
        'id': publicacion.pk,
        'huella_texto': _huella([publicacion.titulo, publicacion.contenido]),
        'temas_previos': {
            'cantidad': len(temas), 'ids': [fila['id'] for fila in temas], 'sha256': _huella(temas),
        },
        'etiquetas_previas': {
            'cantidad': len(etiquetas), 'ids': [fila['id'] for fila in etiquetas], 'sha256': _huella(etiquetas),
        },
    }


def _propuesta_manifiesto(publicacion, tiene_categoria, tiene_etiquetas):
    resultado, propuestas = proponer(publicacion, tiene_categoria, tiene_etiquetas)
    return {
        'clasificacion': resultado['clasificacion'],
        'categoria': resultado['categoria'],
        'etiquetado': resultado['etiquetado'],
        'etiquetas': [{'slug': slug, 'nombre': nombre} for slug, nombre in propuestas],
    }, propuestas


def _plan(filas):
    plan = []
    for publicacion, temas, etiquetas in filas:
        if temas and etiquetas:
            raise LoteInvalido(f'La publicación {publicacion.pk} ya tiene tema y etiquetas.')
        propuesta, propuestas = _propuesta_manifiesto(publicacion, bool(temas), bool(etiquetas))
        entrada = {**_estado_publicacion(publicacion, temas, etiquetas), **propuesta}
        plan.append((publicacion, entrada, propuestas))
    return plan


def _contenido(ids, excluidos, plan):
    return {
        'formato': 1, 'ids': sorted(ids), 'ids_excluidos': sorted(excluidos),
        'versiones': _versiones(), 'publicaciones': [entrada for _, entrada, _ in plan],
    }


def simular_lote_exacto(ids, excluidos):
    _ids_validos(ids, excluidos)
    contenido = _contenido(ids, excluidos, _plan(_leer_estado(ids)))
    return {'contenido': contenido, 'sha256': _huella(contenido)}


def _verificar_manifiesto(manifiesto, aprobado):
    if not isinstance(manifiesto, dict) or manifiesto.keys() != {'contenido', 'sha256'}:
        raise LoteInvalido('Estructura de manifiesto inválida.')
    contenido = manifiesto['contenido']
    if (not isinstance(contenido, dict)
            or contenido.keys() != {'formato', 'ids', 'ids_excluidos', 'versiones', 'publicaciones'}
            or type(contenido['formato']) is not int or contenido['formato'] != 1
            or contenido['versiones'] != _versiones()):
        raise LoteInvalido('Formato o versiones de analizadores incompatibles.')
    ids, excluidos = contenido['ids'], contenido['ids_excluidos']
    _ids_validos(ids, excluidos)
    try:
        digest = _huella(contenido)
    except (ValueError, UnicodeError) as error:
        raise LoteInvalido('Contenido de manifiesto inválido.') from error
    if (manifiesto['sha256'] != digest or not isinstance(aprobado, str)
            or not aprobado.isascii() or not compare_digest(digest, aprobado)):
        raise LoteInvalido('El manifiesto no coincide con el SHA-256 aprobado.')
    return contenido, digest


def _huella_estado(filas):
    return _huella([_estado_publicacion(*fila) for fila in filas])


@transaction.atomic
def aplicar_lote_exacto(manifiesto, aprobado):
    contenido, digest = _verificar_manifiesto(manifiesto, aprobado)
    ids, excluidos = contenido['ids'], contenido['ids_excluidos']
    filas = _leer_estado(ids, bloquear=True)
    comprobante = AplicacionLoteEnriquecimientoLocal.objects.filter(pk=digest).first()
    if comprobante is not None:
        if comprobante.huella_resultante != _huella_estado(filas):
            raise LoteInvalido('El estado posterior a la aplicación cambió.')
        for (publicacion, _, _), entrada in zip(filas, contenido['publicaciones'], strict=True):
            propuesta, _ = _propuesta_manifiesto(
                publicacion, bool(entrada['temas_previos']['cantidad']),
                bool(entrada['etiquetas_previas']['cantidad']),
            )
            if any(entrada[campo] != valor for campo, valor in propuesta.items()):
                raise LoteInvalido('Cambiaron las propuestas desde la aplicación anterior.')
        return {'estado': 'ya_aplicado', 'ids': sorted(ids), 'sha256': digest}

    plan = _plan(filas)
    if _huella(_contenido(ids, excluidos, plan)) != digest:
        raise LoteInvalido('Cambió el contenido, las asociaciones o las propuestas del lote.')

    # Los escritores normales toman primero la publicación, luego etiquetas y
    # finalmente el catálogo temático. Orden global de IDs y slugs aun si el
    # operador enumera los artículos en otro orden.
    catalogo = {}
    for _, _, propuestas in plan:
        for slug, nombre in propuestas:
            catalogo.setdefault(slug, nombre)
    asegurar_catalogo_etiquetas(catalogo.items(), using=filas[0][0]._state.db)
    resultados = []
    for publicacion, entrada, propuestas in plan:
        total = guardar_etiquetas_propuestas(publicacion, propuestas)
        resultados.append({'id': publicacion.pk, 'categoria': entrada['categoria'], 'etiquetas_creadas': total})
    for publicacion, entrada, _ in plan:
        if entrada['categoria']:
            vincular_categoria_por_nombre(
                publicacion, entrada['categoria'],
                procedencia_analisis=procedencia(Metodo.REGLAS, VERSION_CLASIFICACION_LOCAL),
            )
    AplicacionLoteEnriquecimientoLocal.objects.create(
        sha256=digest, huella_resultante=_huella_estado(_leer_estado(ids)),
    )
    return {'estado': 'aplicado', 'ids': sorted(ids), 'sha256': digest, 'resultados': resultados}
