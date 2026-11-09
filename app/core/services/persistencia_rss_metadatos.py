"""Persistencia opt-in de fichas RSS, sin HTML, análisis ni contenido editorial extra."""
from datetime import datetime, timedelta
import math

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from core.models import ControlSolicitudRSSMetadatos, Publicacion, RegistroDatos
from core.services.fuentes_rss import FUENTES_RSS, FuenteRSS
from core.services.lector_rss import NoticiaRSS, ResultadoRSS, leer_rss, normalizar_url
from core.services.persistencia_multifuente import (
    ConflictoIdentidad,
    bloquear_fuente_rss,
    hash_identidad_fuente_url,
    resolver_publicacion_por_identidad,
    vincular_aliases_rss,
)
from core.services.descarga_segura import RespuestaHTTPError


MAXIMO_POR_EJECUCION = 5


class AutorizacionMetadatosError(ValueError):
    """La fuente no está autorizada en configuración o falta confirmación puntual."""


class FuenteRSSEnEspera(ValueError):
    """No venció el intervalo mínimo o el Retry-After del servidor."""

    def __init__(self, segundos):
        self.segundos = max(1, int(segundos))
        super().__init__('La fuente está dentro de su intervalo de espera.')


def _fuente_canonica(fuente_id):
    if not isinstance(fuente_id, str):
        raise ValueError('ID de fuente inválido.')
    fuente = next((f for f in FUENTES_RSS if f.identificador == fuente_id), None)
    if type(fuente) is not FuenteRSS:
        raise ValueError('Fuente desconocida.')
    return fuente


def _ids_configurados(nombre):
    autorizadas = getattr(settings, nombre, ())
    if not isinstance(autorizadas, (tuple, list)) or any(
        not isinstance(valor, str) or not valor for valor in autorizadas
    ):
        raise ImproperlyConfigured(f'{nombre} debe ser una lista de IDs.')
    ids = {fuente.identificador for fuente in FUENTES_RSS}
    if len(set(autorizadas)) != len(autorizadas) or not set(autorizadas) <= ids:
        raise ImproperlyConfigured(f'{nombre} contiene IDs inválidos o duplicados.')
    return frozenset(autorizadas)


def _mapa_configurado(nombre, *, maximo=None):
    mapa = getattr(settings, nombre, {})
    ids = {fuente.identificador for fuente in FUENTES_RSS}
    if (not isinstance(mapa, dict)
            or any(not isinstance(clave, str) or clave not in ids
                   or type(valor) is not int or valor <= 0
                   or (maximo is not None and valor > maximo)
                   for clave, valor in mapa.items())):
        raise ImproperlyConfigured(f'{nombre} contiene IDs o valores inválidos.')
    return mapa


def _politica_fuente(fuente):
    habilitadas = _ids_configurados('RSS_METADATOS_FUENTES_HABILITADAS')
    revisadas = _ids_configurados('RSS_METADATOS_FUENTES_REVISADAS')
    autorizadas = _ids_configurados('RSS_METADATOS_FUENTES_AUTORIZADAS')
    if fuente.identificador not in habilitadas:
        raise AutorizacionMetadatosError('La fuente no está habilitada para ingesta RSS de metadatos.')
    if fuente.identificador not in revisadas:
        raise AutorizacionMetadatosError('Falta revisión documentada de acceso para esta fuente.')
    if fuente.identificador not in autorizadas:
        raise AutorizacionMetadatosError('La fuente no está autorizada para persistencia RSS de metadatos.')
    limites = _mapa_configurado('RSS_METADATOS_LIMITES_POR_FUENTE', maximo=MAXIMO_POR_EJECUCION)
    intervalos = _mapa_configurado('RSS_METADATOS_INTERVALOS_SEGUNDOS_POR_FUENTE')
    if fuente.identificador not in limites:
        raise AutorizacionMetadatosError('Falta un límite operativo explícito para esta fuente.')
    if fuente.identificador not in intervalos:
        raise AutorizacionMetadatosError('Falta un intervalo mínimo explícito para esta fuente.')
    fallback = getattr(settings, 'RSS_METADATOS_429_SIN_RETRY_AFTER_SEGUNDOS', None)
    if type(fallback) is not int or fallback <= 0:
        raise ImproperlyConfigured('RSS_METADATOS_429_SIN_RETRY_AFTER_SEGUNDOS debe ser positivo.')
    return limites[fuente.identificador], intervalos[fuente.identificador], fallback


def _validar_limite(limite, fuente, limite_fuente):
    if type(limite) is not int or not 1 <= limite <= MAXIMO_POR_EJECUCION:
        raise ValueError(f'El límite debe estar entre 1 y {MAXIMO_POR_EJECUCION}.')
    maximo = min(limite_fuente, fuente.limite_noticias, MAXIMO_POR_EJECUCION)
    if limite > maximo:
        raise ValueError(f'El límite solicitado supera el máximo configurado para {fuente.identificador}.')
    return limite


def _reservar_solicitud(fuente, intervalo_segundos):
    """Persiste el intento antes del GET y serializa por fuente entre procesos."""
    # El flujo H5.4 escribe también Publicacion/RegistroDatos en la base default.
    using = 'default'
    with transaction.atomic(using=using):
        bloquear_fuente_rss(fuente, using=using)
        control = (ControlSolicitudRSSMetadatos.objects.using(using)
                   .select_for_update().filter(fuente_id=fuente.identificador).first())
        ahora = timezone.now()
        if control is None:
            control = ControlSolicitudRSSMetadatos.objects.using(using).create(
                fuente_id=fuente.identificador,
            )
        hasta = control.retry_after_hasta
        if hasta and hasta > ahora:
            raise FuenteRSSEnEspera(math.ceil((hasta - ahora).total_seconds()))
        ultimo = control.ultimo_intento
        siguiente = ultimo + timedelta(seconds=intervalo_segundos) if ultimo else None
        if siguiente and siguiente > ahora:
            raise FuenteRSSEnEspera(math.ceil((siguiente - ahora).total_seconds()))
        control.ultimo_intento = ahora
        control.retry_after_hasta = None
        control.save(update_fields=['ultimo_intento', 'retry_after_hasta', 'actualizado'], using=using)
        return control.pk


def _guardar_retry_after(fuente, control_id, segundos):
    using = 'default'
    with transaction.atomic(using=using):
        bloquear_fuente_rss(fuente, using=using)
        control = ControlSolicitudRSSMetadatos.objects.using(using).select_for_update().get(pk=control_id)
        hasta = timezone.now() + timedelta(seconds=segundos)
        if control.retry_after_hasta is None or control.retry_after_hasta < hasta:
            control.retry_after_hasta = hasta
            control.save(update_fields=['retry_after_hasta', 'actualizado'], using=using)


def _validar_item(item, fuente):
    if type(item) is not NoticiaRSS:
        raise ValueError('Entrada RSS no normalizada.')
    if item.fuente_id != fuente.identificador or item.fuente != fuente.nombre:
        raise ValueError('Identidad de fuente inconsistente.')
    titulo = item.titulo
    if (not isinstance(titulo, str) or not titulo.strip() or len(titulo) > 255
            or any((ord(c) < 32 and c not in '\n\r\t') or ord(c) == 127 for c in titulo)):
        raise ValueError('Título RSS inválido.')
    url = normalizar_url(item.url, fuente)
    if len(url) > Publicacion._meta.get_field('url').max_length:
        raise ValueError('URL RSS demasiado larga.')
    fecha = item.fecha
    if fecha is not None and (not isinstance(fecha, datetime) or timezone.is_naive(fecha)):
        raise ValueError('Fecha RSS inválida.')
    hash_origen = hash_identidad_fuente_url(fuente, url)
    return titulo, url, fecha, hash_origen


def _persistir_item(fuente, noticia, campos, registro):
    titulo, url, fecha, hash_origen = campos
    aliases = {url}
    for intento in range(3):
        try:
            with transaction.atomic():
                bloquear_fuente_rss(fuente)
                existente = resolver_publicacion_por_identidad(fuente, hash_origen, aliases)
                if existente is not None:
                    vincular_aliases_rss(fuente, aliases, existente)
                    return existente, False

                publicacion = Publicacion(
                    hash_origen=hash_origen,
                    fuente=fuente.nombre,
                    titulo=titulo,
                    url=url,
                    fecha_publicacion=fecha,
                    contenido='',
                    contenido_completo=False,
                    procesado_ia=False,
                    departamento='',
                    id_registro=registro,
                )
                publicacion.full_clean(
                    exclude=['titulo_busqueda', 'contenido_busqueda'],
                    validate_unique=False,
                    validate_constraints=False,
                )
                publicacion.save(force_insert=True)
                vincular_aliases_rss(fuente, aliases, publicacion.pk)
                # No se crean categoría, etiquetas, sentimiento ni reserva IA.
                return publicacion.pk, True
        except DatabaseError as exc:
            causa = exc.__cause__
            codigo = getattr(causa, 'sqlstate', None) or getattr(causa, 'pgcode', None)
            reintentable = isinstance(exc, IntegrityError) or codigo in ('40001', '40P01')
            if intento == 2 or not reintentable:
                raise


def _codigo_rechazo(motivo):
    texto = str(motivo).lower()
    if 'título' in texto or 'titulo' in texto:
        return 'titulo_invalido'
    if 'fecha' in texto or 'offset' in texto:
        return 'fecha_invalida'
    if 'url' in texto or 'host' in texto or 'destino' in texto:
        return 'url_invalida'
    return 'entrada_rss_invalida'


def _resultado_base(fuente_id, limite):
    return {
        'fuente_id': fuente_id,
        'limite': limite,
        'registro_id': None,
        'nuevas': 0,
        'duplicadas': 0,
        'rechazadas': 0,
        'errores': 0,
        'espera_segundos': None,
        'causas': [],
        'noticias': [],
    }


def persistir_metadatos_rss(fuente_id, *, limite=1, confirmar_persistencia=False, lector=None):
    """Lee un feed vía H2.1/H2.2 y persiste sólo fuente, título, fecha y enlace.

    Habilitación, revisión de acceso, autorización de persistencia, límite,
    intervalo y confirmación puntual son barreras independientes. La bandera
    H1.1 `habilitada` no se modifica ni activa el pipeline de cuerpo completo.
    """
    fuente = _fuente_canonica(fuente_id)
    if type(limite) is not int or not 1 <= limite <= MAXIMO_POR_EJECUCION:
        raise ValueError(f'El límite debe estar entre 1 y {MAXIMO_POR_EJECUCION}.')
    if confirmar_persistencia is not True:
        raise AutorizacionMetadatosError('Falta --confirmar-persistencia.')
    maximo_fuente, intervalo_segundos, fallback_429 = _politica_fuente(fuente)
    limite = _validar_limite(limite, fuente, maximo_fuente)

    resultado = _resultado_base(fuente.identificador, limite)
    try:
        control_id = _reservar_solicitud(fuente, intervalo_segundos)
    except FuenteRSSEnEspera as exc:
        resultado.update(estado='BLOQUEADA', errores=1, espera_segundos=exc.segundos)
        resultado['causas'].append({'codigo': 'intervalo_minimo_no_vencido',
                                    'reintentar_en_segundos': exc.segundos})
        return resultado
    except DatabaseError as exc:
        resultado.update(estado='ERROR', errores=1)
        resultado['causas'].append({'codigo': 'control_de_frecuencia_no_disponible',
                                    'tipo': type(exc).__name__})
        return resultado
    try:
        lector = lector or leer_rss
        lectura = lector(fuente, limite_entradas=limite)
        if type(lectura) is not ResultadoRSS:
            raise ValueError('El lector RSS devolvió un resultado inválido.')
    except Exception as exc:
        resultado.update(estado='ERROR', errores=1)
        resultado['causas'].append({'codigo': 'consulta_rss_fallida', 'tipo': type(exc).__name__})
        if isinstance(exc, RespuestaHTTPError):
            causa = resultado['causas'][-1]
            causa['http_status'] = exc.estado
            if exc.estado == 429:
                espera = exc.retry_after_segundos
                if espera is None:
                    espera = fallback_429
                try:
                    _guardar_retry_after(fuente, control_id, espera)
                except DatabaseError:
                    causa['codigo'] = 'http_429_retry_after_no_persistido'
                    causa['bloqueo_operativo_manual_requerido'] = True
                resultado['espera_segundos'] = espera
                if causa['codigo'] != 'http_429_retry_after_no_persistido':
                    causa['codigo'] = 'http_429'
                causa['reintentar_en_segundos'] = espera
        return resultado

    # H2.2 limita por índice original. No contar rechazos de entradas posteriores
    # al límite de esta ejecución.
    rechazos = [(indice, motivo) for indice, motivo in lectura.rechazos if indice < limite]
    resultado['rechazadas'] = len(rechazos)
    resultado['causas'].extend(
        {'indice': indice, 'codigo': _codigo_rechazo(motivo)} for indice, motivo in rechazos
    )
    registro = RegistroDatos.objects.create(
        fuentes_api=f'RSS metadatos: {fuente.identificador}',
        fecha_ejecucion=timezone.now(),
        estado='EN_PROCESO',
        lenguaje='es',
    )
    resultado['registro_id'] = registro.pk

    for indice, noticia in enumerate(lectura.noticias[:limite]):
        try:
            campos = _validar_item(noticia, fuente)
            publicacion_id, creada = _persistir_item(fuente, noticia, campos, registro)
            clave = 'nuevas' if creada else 'duplicadas'
            resultado[clave] += 1
            resultado['noticias'].append({
                'indice': indice,
                'estado': 'NUEVA' if creada else 'DUPLICADA',
                'publicacion_id': publicacion_id,
            })
        except ConflictoIdentidad as exc:
            resultado['errores'] += 1
            resultado['causas'].append({'indice': indice, 'codigo': 'conflicto_identidad'})
        except (ValueError, ValidationError, TypeError) as exc:
            resultado['rechazadas'] += 1
            resultado['causas'].append({'indice': indice, 'codigo': 'metadatos_invalidos'})
        except Exception as exc:
            resultado['errores'] += 1
            resultado['causas'].append({'indice': indice, 'codigo': 'persistencia_fallida',
                                        'tipo': type(exc).__name__})

    hay_resultados = resultado['nuevas'] or resultado['duplicadas']
    hay_fallos = resultado['rechazadas'] or resultado['errores']
    estado = 'PARCIAL' if hay_resultados and hay_fallos else 'ERROR' if hay_fallos else 'EXITO'
    registro.estado = estado
    registro.save(update_fields=['estado'])
    resultado['estado'] = estado
    return resultado
