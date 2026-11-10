"""Lotes RSS con snapshot de metadatos y checkpoint por entrada."""
from datetime import datetime
import json
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from core.models import RegistroDatos, TrabajoLoteRSSMetadatos
from core.services.fuentes_rss import FUENTES_RSS
from core.services.lector_rss import NoticiaRSS, ResultadoRSS, leer_rss
from core.services.persistencia_multifuente import bloquear_fuente_rss
from core.services.persistencia_rss_metadatos import (
    MAXIMO_POR_EJECUCION,
    AutorizacionMetadatosError,
    FuenteBloqueada,
    FuenteRSSEnEspera,
    _codigo_rechazo,
    _finalizar_solicitud,
    _fuente_canonica,
    _persistir_item,
    _politica_fuente,
    _reservar_solicitud,
    _validar_item,
)
from core.services.descarga_segura import RespuestaHTTPError
from core.services.contrato_historico_lotes import (
    MAX_BYTES_PAQUETE,
    MAX_ENTRADAS_HISTORICAS,
    MetadatosHistoricosInvalidos,
    adaptar_candidatas,
)

MAXIMO_SNAPSHOT = 30
ESTADOS_ABIERTOS = (
    TrabajoLoteRSSMetadatos.Estado.PENDIENTE,
    TrabajoLoteRSSMetadatos.Estado.EN_PROGRESO,
    TrabajoLoteRSSMetadatos.Estado.PAUSADO,
)


class TokenEjecutorPerdido(ValueError):
    """Un ejecutor antiguo fue cercado por una recuperación explícita."""


def _reporte(trabajo):
    pendientes = sum(item.get('estado') == 'PENDIENTE' for item in trabajo.snapshot)
    return {
        'trabajo_id': trabajo.pk,
        'fuente_id': trabajo.fuente_id,
        'origen': trabajo.origen,
        'estado': trabajo.estado,
        'tamano_lote': trabajo.tamano_lote,
        # Mantener el valor histórico de RSS y no atribuir un feed a trabajos
        # históricos. Las claves nuevas son aditivas para los consumidores.
        'entradas_feed': (trabajo.entradas_feed
                          if trabajo.origen == TrabajoLoteRSSMetadatos.Origen.RSS else 0),
        'entradas_historicas': (trabajo.entradas_snapshot
                                if trabajo.origen == TrabajoLoteRSSMetadatos.Origen.HISTORICO else 0),
        'entradas_snapshot': trabajo.entradas_snapshot,
        'entradas_fuera_snapshot': trabajo.entradas_fuera_snapshot,
        'procesadas': trabajo.procesadas,
        'entradas_pendientes': pendientes,
        'nuevas': trabajo.nuevas,
        'persistidas': trabajo.nuevas,
        'duplicadas': trabajo.duplicadas,
        'rechazadas': trabajo.rechazadas,
        'errores': trabajo.errores,
        'resultados': trabajo.resultados,
        'codigo_error': trabajo.codigo_error or None,
        'registro_id': trabajo.registro_id,
        'actualizado': trabajo.actualizado.isoformat(),
        'finalizado': trabajo.finalizado.isoformat() if trabajo.finalizado else None,
    }


def _validar_barreras(fuente_id, tamano_lote, confirmar_persistencia, *, origen='RSS'):
    if confirmar_persistencia is not True:
        raise AutorizacionMetadatosError('Falta --confirmar-persistencia.')
    fuente = _fuente_canonica(fuente_id)
    if origen == TrabajoLoteRSSMetadatos.Origen.RSS and fuente.solo_importacion_historica:
        raise AutorizacionMetadatosError('La fuente sólo admite importación histórica; no se hará un GET RSS.')
    if origen == TrabajoLoteRSSMetadatos.Origen.HISTORICO and not fuente.solo_importacion_historica:
        raise AutorizacionMetadatosError('La fuente no está declarada como importación histórica.')
    if origen not in TrabajoLoteRSSMetadatos.Origen.values:
        raise ValueError('Origen de trabajo inválido.')
    maximo, intervalo, fallback_429 = _politica_fuente(fuente)
    maximo_lote = min(maximo, fuente.limite_noticias, MAXIMO_POR_EJECUCION)
    if type(tamano_lote) is not int or not 1 <= tamano_lote <= maximo_lote:
        raise ValueError(f'El tamaño de lote debe estar entre 1 y {maximo_lote}.')
    return fuente, intervalo, fallback_429


def _crear_trabajo(fuente, tamano_lote, *, origen=TrabajoLoteRSSMetadatos.Origen.RSS):
    token = uuid4()
    try:
        with transaction.atomic():
            bloquear_fuente_rss(fuente)
            if TrabajoLoteRSSMetadatos.objects.filter(
                fuente_id=fuente.identificador, estado__in=ESTADOS_ABIERTOS,
            ).exists():
                raise ValueError('Ya existe un trabajo abierto para esta fuente.')
            return TrabajoLoteRSSMetadatos.objects.create(
                fuente_id=fuente.identificador,
                origen=origen,
                tamano_lote=tamano_lote,
                estado=TrabajoLoteRSSMetadatos.Estado.EN_PROGRESO,
                token_ejecutor=token,
            )
    except IntegrityError as exc:
        raise ValueError('Ya existe un trabajo abierto para esta fuente.') from exc


def _estado_fallido(trabajo_id, codigo, *, token=None):
    with transaction.atomic():
        trabajo = TrabajoLoteRSSMetadatos.objects.select_for_update().get(pk=trabajo_id)
        if token is not None and trabajo.token_ejecutor != token:
            return _reporte(trabajo)
        trabajo.estado = TrabajoLoteRSSMetadatos.Estado.FALLIDO
        trabajo.codigo_error = codigo
        trabajo.token_ejecutor = None
        trabajo.finalizado = timezone.now()
        trabajo.save(update_fields=['estado', 'codigo_error', 'token_ejecutor', 'finalizado', 'actualizado'])
        return _reporte(trabajo)


def _registrar_snapshot(trabajo_id, lectura, fuente, token):
    if type(lectura) is not ResultadoRSS:
        raise ValueError('El lector RSS devolvió un resultado inválido.')
    limite = min(fuente.limite_noticias, MAXIMO_SNAPSHOT)
    rechazados = {indice: motivo for indice, motivo in lectura.rechazos if indice < limite}
    if len(lectura.indices_noticias) == len(lectura.noticias):
        indices = lectura.indices_noticias
    else:
        candidatos = (i for i in range(limite) if i not in rechazados)
        indices = tuple(next(candidatos, -1) for _ in lectura.noticias)
    noticias_por_indice = dict(zip(indices, lectura.noticias))
    elementos = []
    total = lectura.total_entradas or (max(
        [*indices, *rechazados.keys()], default=-1,
    ) + 1)
    for indice in range(min(total, limite)):
        if indice in rechazados:
            elementos.append({
                'indice': indice,
                'estado': 'RECHAZADA',
                'codigo': _codigo_rechazo(rechazados[indice]),
            })
            continue
        noticia = noticias_por_indice.get(indice)
        if noticia is None:
            elementos.append({'indice': indice, 'estado': 'RECHAZADA', 'codigo': 'entrada_ausente'})
            continue
        try:
            titulo, url, fecha, _ = _validar_item(noticia, fuente)
            elementos.append({
                'indice': indice,
                'estado': 'PENDIENTE',
                'titulo': titulo,
                'url': url,
                'fecha': fecha.isoformat() if fecha else None,
            })
        except (ValueError, ValidationError, TypeError):
            elementos.append({'indice': indice, 'estado': 'RECHAZADA', 'codigo': 'metadatos_invalidos'})

    truncadas = max(lectura.truncadas, max(0, total - limite))
    with transaction.atomic():
        trabajo = TrabajoLoteRSSMetadatos.objects.select_for_update().get(pk=trabajo_id)
        if (trabajo.token_ejecutor != token
                or trabajo.estado != TrabajoLoteRSSMetadatos.Estado.EN_PROGRESO):
            raise TokenEjecutorPerdido('La solicitud terminó después de perder su reserva de trabajo.')
        trabajo.snapshot = elementos
        trabajo.entradas_feed = total
        trabajo.entradas_snapshot = len(elementos)
        trabajo.entradas_fuera_snapshot = truncadas
        trabajo.rechazadas = sum(1 for item in elementos if item['estado'] == 'RECHAZADA')
        trabajo.procesadas = trabajo.rechazadas
        trabajo.resultados = [
            {'indice': item['indice'], 'estado': 'RECHAZADA', 'codigo': item['codigo']}
            for item in elementos if item['estado'] == 'RECHAZADA'
        ]
        registro = RegistroDatos.objects.create(
            fuentes_api=f'RSS metadatos por lotes: {fuente.identificador}',
            fecha_ejecucion=timezone.now(),
            estado='EN_PROCESO',
            lenguaje='es',
        )
        trabajo.registro = registro
        trabajo.save(update_fields=[
            'snapshot', 'entradas_feed', 'entradas_snapshot', 'entradas_fuera_snapshot',
            'rechazadas', 'procesadas', 'resultados', 'registro', 'actualizado',
        ])
    return total, truncadas


def _crear_trabajo_historico(fuente_id, tamano_lote, descubrimiento, verificaciones,
                             confirmar_persistencia):
    """Valida el contrato y crea trabajo, auditoría y snapshot; nunca hace GET."""
    if not getattr(settings, 'HISTORICO_IMPORTACION_HABILITADA', False):
        raise AutorizacionMetadatosError(
            'La importación histórica está deshabilitada hasta contar con verificación de evidencia.'
        )
    fuente, _, _ = _validar_barreras(
        fuente_id, tamano_lote, confirmar_persistencia,
        origen=TrabajoLoteRSSMetadatos.Origen.HISTORICO,
    )
    paquete = {'descubrimiento': descubrimiento, 'verificaciones': verificaciones}
    try:
        tamano_paquete = len(json.dumps(
            paquete, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
        ).encode('utf-8'))
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise MetadatosHistoricosInvalidos('paquete no serializable') from exc
    if tamano_paquete > MAX_BYTES_PAQUETE:
        raise MetadatosHistoricosInvalidos('paquete histórico supera el tamaño máximo')
    convertido = adaptar_candidatas(descubrimiento, verificaciones)
    entradas = convertido['entradas']
    if (convertido['rechazadas'] or convertido['duplicadas']
            or not 1 <= len(entradas) <= min(MAXIMO_SNAPSHOT, MAX_ENTRADAS_HISTORICAS)):
        raise MetadatosHistoricosInvalidos(
            'el paquete debe contener sólo entradas verificadas, únicas y dentro del límite'
        )

    instantanea = []
    procedencia = {
        'fuente_id': fuente.identificador,
        'tipo': 'metadatos_historicos_verificados',
        'entradas': [],
    }
    identidades = set()
    for indice, entrada in enumerate(entradas):
        if (entrada.noticia.fuente_id != fuente.identificador
                or entrada.noticia.fuente != fuente.nombre
                or entrada.noticia.resumen or entrada.noticia.contenido_completo
                or entrada.noticia.seccion):
            raise MetadatosHistoricosInvalidos('la fuente o los campos de contenido no corresponden al contrato')
        titulo, url, fecha, hash_origen = _validar_item(entrada.noticia, fuente)
        if hash_origen in identidades:
            raise ValueError('El snapshot histórico contiene URLs duplicadas.')
        identidades.add(hash_origen)
        instantanea.append({
            'indice': indice,
            'estado': 'PENDIENTE',
            'titulo': titulo,
            'url': url,
            'fecha': fecha.isoformat() if fecha else None,
        })
        procedencia['entradas'].append({
            'indice': indice,
            'url_identidad': entrada.procedencia['url_identidad'],
            'lastmod_sitemap': entrada.lastmod_sitemap,
            'verificacion': entrada.procedencia.get('verificacion'),
        })

    token = uuid4()
    try:
        with transaction.atomic():
            bloquear_fuente_rss(fuente)
            if TrabajoLoteRSSMetadatos.objects.filter(
                fuente_id=fuente.identificador, estado__in=ESTADOS_ABIERTOS,
            ).exists():
                raise ValueError('Ya existe un trabajo abierto para esta fuente.')
            registro = RegistroDatos.objects.create(
                fuentes_api=f'Importación histórica por lotes: {fuente.identificador}',
                fecha_ejecucion=timezone.now(),
                estado='EN_PROCESO',
                lenguaje='es',
            )
            trabajo = TrabajoLoteRSSMetadatos.objects.create(
                fuente_id=fuente.identificador,
                origen=TrabajoLoteRSSMetadatos.Origen.HISTORICO,
                procedencia=procedencia,
                tamano_lote=tamano_lote,
                snapshot=instantanea,
                entradas_feed=0,
                entradas_snapshot=len(instantanea),
                estado=TrabajoLoteRSSMetadatos.Estado.EN_PROGRESO,
                token_ejecutor=token,
                registro=registro,
            )
            return trabajo, token, fuente
    except IntegrityError as exc:
        raise ValueError('Ya existe un trabajo abierto para esta fuente.') from exc


def iniciar_lote_historico(fuente_id, descubrimiento, verificaciones, *, tamano_lote=1,
                           confirmar_persistencia=False):
    """Valida el paquete H5.10-D y procesa su snapshot sin GET.

    La importación permanece deshabilitada por defecto mientras no exista una
    fuente de evidencia auténtica revisable. El flag de configuración habilita
    operación, pero no se considera prueba de autenticidad.
    """
    trabajo, token, fuente = _crear_trabajo_historico(
        fuente_id, tamano_lote, descubrimiento, verificaciones,
        confirmar_persistencia,
    )
    return _procesar_con_token(trabajo.pk, token, fuente)


def iniciar_lote(fuente_id, *, tamano_lote=1, confirmar_persistencia=False, lector=None):
    """Hace como máximo un GET, conserva un snapshot acotado y procesa un chunk."""
    fuente, intervalo, fallback_429 = _validar_barreras(
        fuente_id, tamano_lote, confirmar_persistencia,
    )
    trabajo = _crear_trabajo(fuente, tamano_lote)
    token = trabajo.token_ejecutor
    try:
        control_id = _reservar_solicitud(fuente, intervalo)
    except FuenteRSSEnEspera:
        return _estado_fallido(trabajo.pk, 'intervalo_minimo_no_vencido', token=token)
    except FuenteBloqueada:
        return _estado_fallido(trabajo.pk, 'solicitud_previa_pendiente', token=token)
    except DatabaseError:
        return _estado_fallido(trabajo.pk, 'control_frecuencia_no_disponible', token=token)

    try:
        lector = lector or leer_rss
        lectura = lector(fuente, limite_entradas=min(fuente.limite_noticias, MAXIMO_SNAPSHOT))
        _registrar_snapshot(trabajo.pk, lectura, fuente, token)
    except TokenEjecutorPerdido:
        # La recuperación cercó este proceso; nunca debe reactivar el trabajo.
        return consultar_trabajo(trabajo.pk)
    except Exception as exc:
        codigo = 'http_429' if isinstance(exc, RespuestaHTTPError) and exc.estado == 429 else 'consulta_rss_fallida'
        retry_after = None
        revision_manual = False
        if isinstance(exc, RespuestaHTTPError) and exc.estado == 429:
            if exc.retry_after_excesivo:
                revision_manual = True
                codigo = 'http_429_retry_after_excesivo'
            else:
                retry_after = (fallback_429 if exc.retry_after_segundos is None
                               else exc.retry_after_segundos)
        try:
            _finalizar_solicitud(
                fuente, control_id, intervalo,
                retry_after_segundos=retry_after,
                revision_manual=revision_manual,
            )
        except (DatabaseError, FuenteBloqueada):
            codigo = 'solicitud_fuente_pendiente_revision'
        return _estado_fallido(trabajo.pk, codigo, token=token)

    try:
        _finalizar_solicitud(fuente, control_id, intervalo)
    except (DatabaseError, FuenteBloqueada):
        # El snapshot ya es durable; puede procesarse sin otro GET, pero H5.6
        # mantiene la fuente bloqueada para cualquier solicitud posterior.
        TrabajoLoteRSSMetadatos.objects.filter(pk=trabajo.pk, token_ejecutor=token).update(
            codigo_error='control_fuente_pendiente_revision',
        )
    try:
        return _procesar_con_token(trabajo.pk, token, fuente)
    except TokenEjecutorPerdido:
        return consultar_trabajo(trabajo.pk)


def _reclamar(trabajo_id):
    with transaction.atomic():
        trabajo = TrabajoLoteRSSMetadatos.objects.select_for_update().get(pk=trabajo_id)
        if trabajo.estado not in (TrabajoLoteRSSMetadatos.Estado.PENDIENTE,
                                  TrabajoLoteRSSMetadatos.Estado.PAUSADO):
            raise ValueError('El trabajo no está disponible para procesar o reanudar.')
        if trabajo.token_ejecutor is not None:
            raise ValueError('El trabajo ya tiene un procesador activo.')
        if not trabajo.snapshot:
            raise ValueError('No hay un snapshot durable para reanudar; no se realizará otro GET.')
        fuente = _fuente_canonica(trabajo.fuente_id)
        token = uuid4()
        trabajo.estado = TrabajoLoteRSSMetadatos.Estado.EN_PROGRESO
        trabajo.token_ejecutor = token
        trabajo.pausa_solicitada = False
        trabajo.save(update_fields=['estado', 'token_ejecutor', 'pausa_solicitada', 'actualizado'])
        return token, fuente


def _marcar_item(trabajo, item_index, *, estado, codigo=None, publicacion_id=None):
    item = trabajo.snapshot[item_index]
    item['estado'] = estado
    resultados = list(trabajo.resultados)
    resultados.append({
        'indice': item['indice'], 'estado': estado,
        **({'codigo': codigo} if codigo else {}),
        **({'publicacion_id': publicacion_id} if publicacion_id else {}),
    })
    trabajo.snapshot[item_index] = item
    trabajo.resultados = resultados
    trabajo.procesadas += 1
    if estado == 'NUEVA':
        trabajo.nuevas += 1
    elif estado == 'DUPLICADA':
        trabajo.duplicadas += 1
    elif estado == 'RECHAZADA':
        trabajo.rechazadas += 1
    else:
        trabajo.errores += 1


def _guardar_error_item(trabajo_id, token, item_index, codigo):
    with transaction.atomic():
        trabajo = TrabajoLoteRSSMetadatos.objects.select_for_update().get(pk=trabajo_id)
        if trabajo.token_ejecutor != token:
            raise TokenEjecutorPerdido('Se perdió la reserva de procesamiento del trabajo.')
        _marcar_item(trabajo, item_index, estado='ERROR', codigo=codigo)
        trabajo.save(update_fields=['snapshot', 'resultados', 'procesadas', 'errores', 'actualizado'])


def _procesar_item(trabajo_id, token, item_index, fuente):
    with transaction.atomic():
        trabajo = TrabajoLoteRSSMetadatos.objects.select_for_update().get(pk=trabajo_id)
        if trabajo.token_ejecutor != token or trabajo.estado != TrabajoLoteRSSMetadatos.Estado.EN_PROGRESO:
            raise TokenEjecutorPerdido('La reserva de procesamiento cambió.')
        item = trabajo.snapshot[item_index]
        if item['estado'] != 'PENDIENTE':
            return False
        fecha = datetime.fromisoformat(item['fecha']) if item.get('fecha') else None
        noticia = NoticiaRSS(
            fuente.nombre, fuente.identificador, item['titulo'], item['url'], fecha,
            '', '', '',
        )
        campos = _validar_item(noticia, fuente)
        publicacion_id, creada = _persistir_item(
            fuente, noticia, campos, RegistroDatos.objects.get(pk=trabajo.registro_id),
        )
        _marcar_item(
            trabajo, item_index,
            estado='NUEVA' if creada else 'DUPLICADA',
            publicacion_id=publicacion_id,
        )
        trabajo.save(update_fields=['snapshot', 'resultados', 'procesadas', 'nuevas', 'duplicadas', 'actualizado'])
        return True


def _solicitar_pausa(trabajo):
    if trabajo.estado == TrabajoLoteRSSMetadatos.Estado.EN_PROGRESO and trabajo.token_ejecutor:
        trabajo.pausa_solicitada = True
    elif trabajo.estado in (TrabajoLoteRSSMetadatos.Estado.PENDIENTE,
                            TrabajoLoteRSSMetadatos.Estado.PAUSADO):
        trabajo.estado = TrabajoLoteRSSMetadatos.Estado.PAUSADO
    else:
        raise ValueError('Sólo se pueden pausar trabajos pendientes o activos.')
    trabajo.save(update_fields=['pausa_solicitada', 'estado', 'actualizado'])


def procesar_lote(trabajo_id, *, confirmar_persistencia=False):
    """Procesa un chunk desde el snapshot, con un checkpoint por elemento."""
    trabajo = TrabajoLoteRSSMetadatos.objects.get(pk=trabajo_id)
    _validar_barreras(
        trabajo.fuente_id, trabajo.tamano_lote, confirmar_persistencia,
        origen=trabajo.origen,
    )
    token, fuente = _reclamar(trabajo_id)
    return _procesar_con_token(trabajo_id, token, fuente)


def _procesar_con_token(trabajo_id, token, fuente):
    trabajo = TrabajoLoteRSSMetadatos.objects.get(pk=trabajo_id)
    if (trabajo.token_ejecutor != token
            or trabajo.estado != TrabajoLoteRSSMetadatos.Estado.EN_PROGRESO):
        raise TokenEjecutorPerdido('El trabajo ya no pertenece a este ejecutor.')
    procesadas_chunk = 0
    try:
        while procesadas_chunk < trabajo.tamano_lote:
            trabajo.refresh_from_db()
            if trabajo.pausa_solicitada:
                break
            indice = next((i for i, item in enumerate(trabajo.snapshot)
                           if item['estado'] == 'PENDIENTE'), None)
            if indice is None:
                break
            try:
                _procesar_item(trabajo_id, token, indice, fuente)
            except TokenEjecutorPerdido:
                return consultar_trabajo(trabajo_id)
            except (ValueError, ValidationError, TypeError):
                _guardar_error_item(trabajo_id, token, indice, 'metadatos_invalidos')
            except DatabaseError:
                # Rollback deja publicación y checkpoint sin cambios; el
                # ejecutor se libera debajo y la entrada podrá reanudarse.
                raise
            except Exception:
                # Los errores no recuperables por elemento quedan explícitos.
                if not TrabajoLoteRSSMetadatos.objects.filter(
                    pk=trabajo_id, token_ejecutor=token,
                ).exists():
                    raise
                _guardar_error_item(trabajo_id, token, indice, 'persistencia_fallida')
            procesadas_chunk += 1
        with transaction.atomic():
            trabajo = TrabajoLoteRSSMetadatos.objects.select_for_update().get(pk=trabajo_id)
            if trabajo.token_ejecutor != token:
                raise TokenEjecutorPerdido('Se perdió la reserva de procesamiento del trabajo.')
            quedan = any(item['estado'] == 'PENDIENTE' for item in trabajo.snapshot)
            trabajo.token_ejecutor = None
            trabajo.pausa_solicitada = False
            trabajo.estado = (TrabajoLoteRSSMetadatos.Estado.PAUSADO if quedan
                              else TrabajoLoteRSSMetadatos.Estado.COMPLETADO)
            if not quedan:
                trabajo.finalizado = timezone.now()
                # Al completar se retiran títulos/URLs del snapshot; el resumen
                # de índices/estados queda como auditoría sin contenido editorial.
                trabajo.snapshot = []
            trabajo.save(update_fields=[
                'estado', 'token_ejecutor', 'pausa_solicitada', 'finalizado', 'snapshot', 'actualizado',
            ])
            if trabajo.registro_id:
                fallo = bool(trabajo.rechazadas or trabajo.errores)
                trabajo.registro.estado = 'PARCIAL' if fallo and (trabajo.nuevas or trabajo.duplicadas) else (
                    'ERROR' if fallo else 'EXITO'
                )
                trabajo.registro.save(update_fields=['estado'])
        return _reporte(trabajo)
    except TokenEjecutorPerdido:
        return consultar_trabajo(trabajo_id)
    except BaseException:
        # Excepciones normales/interrupciones cooperativas dejan el cursor
        # durable; SIGKILL conserva token y exige recuperación manual.
        with transaction.atomic():
            trabajo = TrabajoLoteRSSMetadatos.objects.select_for_update().get(pk=trabajo_id)
            if trabajo.token_ejecutor == token:
                trabajo.token_ejecutor = None
                trabajo.estado = TrabajoLoteRSSMetadatos.Estado.PAUSADO
                trabajo.save(update_fields=['token_ejecutor', 'estado', 'actualizado'])
        raise


def consultar_trabajo(trabajo_id):
    """Consulta sólo PostgreSQL; nunca accede al RSS."""
    return _reporte(TrabajoLoteRSSMetadatos.objects.get(pk=trabajo_id))


def pausar_trabajo(trabajo_id):
    with transaction.atomic():
        trabajo = TrabajoLoteRSSMetadatos.objects.select_for_update().get(pk=trabajo_id)
        _solicitar_pausa(trabajo)
        return _reporte(trabajo)


def recuperar_trabajo(trabajo_id, *, confirmar_ejecutor_detenido=False):
    if confirmar_ejecutor_detenido is not True:
        raise ValueError('Falta --confirmar-ejecutor-detenido.')
    with transaction.atomic():
        trabajo = TrabajoLoteRSSMetadatos.objects.select_for_update().get(pk=trabajo_id)
        if trabajo.estado != TrabajoLoteRSSMetadatos.Estado.EN_PROGRESO:
            if trabajo.estado == TrabajoLoteRSSMetadatos.Estado.PENDIENTE and not trabajo.snapshot:
                trabajo.estado = TrabajoLoteRSSMetadatos.Estado.FALLIDO
                trabajo.codigo_error = 'interrupcion_sin_snapshot; revisar_control_h5_6'
                trabajo.finalizado = timezone.now()
                trabajo.save(update_fields=['estado', 'codigo_error', 'finalizado', 'actualizado'])
                return _reporte(trabajo)
            raise ValueError('El trabajo no requiere recuperación de un ejecutor interrumpido.')
        if trabajo.token_ejecutor is None:
            raise ValueError('No hay token de ejecutor pendiente.')
        trabajo.token_ejecutor = None
        trabajo.pausa_solicitada = False
        if trabajo.snapshot:
            trabajo.estado = TrabajoLoteRSSMetadatos.Estado.PAUSADO
            trabajo.codigo_error = ''
            trabajo.save(update_fields=[
                'estado', 'token_ejecutor', 'pausa_solicitada', 'codigo_error', 'actualizado',
            ])
        else:
            # No hay datos durables que reanudar. El control H5.6 queda intacto
            # y requerirá su resolución manual antes de cualquier nuevo GET.
            trabajo.estado = TrabajoLoteRSSMetadatos.Estado.FALLIDO
            trabajo.codigo_error = 'interrupcion_sin_snapshot_revisar_control_h5_6'
            trabajo.finalizado = timezone.now()
            trabajo.save(update_fields=[
                'estado', 'token_ejecutor', 'pausa_solicitada', 'codigo_error',
                'finalizado', 'actualizado',
            ])
        return _reporte(trabajo)


def reanudar_trabajo(trabajo_id, *, confirmar_persistencia=False):
    return procesar_lote(trabajo_id, confirmar_persistencia=confirmar_persistencia)
