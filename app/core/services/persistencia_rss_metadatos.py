"""Persistencia opt-in de fichas RSS, sin HTML, análisis ni contenido editorial extra."""
from datetime import datetime

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from core.models import Publicacion, RegistroDatos
from core.services.fuentes_rss import FUENTES_RSS, FuenteRSS
from core.services.lector_rss import NoticiaRSS, ResultadoRSS, leer_rss, normalizar_url
from core.services.persistencia_multifuente import (
    ConflictoIdentidad,
    bloquear_fuente_rss,
    hash_identidad_fuente_url,
    resolver_publicacion_por_identidad,
    vincular_aliases_rss,
)


MAXIMO_POR_EJECUCION = 5


class AutorizacionMetadatosError(ValueError):
    """La fuente no está autorizada en configuración o falta confirmación puntual."""


def _fuente_canonica(fuente_id):
    if not isinstance(fuente_id, str):
        raise ValueError('ID de fuente inválido.')
    fuente = next((f for f in FUENTES_RSS if f.identificador == fuente_id), None)
    if type(fuente) is not FuenteRSS:
        raise ValueError('Fuente desconocida.')
    return fuente


def _fuentes_autorizadas():
    autorizadas = getattr(settings, 'RSS_METADATOS_FUENTES_AUTORIZADAS', ())
    if not isinstance(autorizadas, (tuple, list)) or any(
        not isinstance(valor, str) or not valor for valor in autorizadas
    ):
        raise ImproperlyConfigured('RSS_METADATOS_FUENTES_AUTORIZADAS debe ser una lista de IDs.')
    ids = {fuente.identificador for fuente in FUENTES_RSS}
    if len(set(autorizadas)) != len(autorizadas) or not set(autorizadas) <= ids:
        raise ImproperlyConfigured('RSS_METADATOS_FUENTES_AUTORIZADAS contiene IDs inválidos o duplicados.')
    return frozenset(autorizadas)


def _validar_limite(limite, fuente):
    if type(limite) is not int or not 1 <= limite <= MAXIMO_POR_EJECUCION:
        raise ValueError(f'El límite debe estar entre 1 y {MAXIMO_POR_EJECUCION}.')
    return min(limite, fuente.limite_noticias)


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
        'causas': [],
        'noticias': [],
    }


def persistir_metadatos_rss(fuente_id, *, limite=1, confirmar_persistencia=False, lector=None):
    """Lee un feed vía H2.1/H2.2 y persiste sólo fuente, título, fecha y enlace.

    `RSS_METADATOS_FUENTES_AUTORIZADAS` y la confirmación por ejecución son
    barreras independientes. La bandera H1.1 `habilitada` no se modifica ni se
    usa para activar el pipeline de artículos completos.
    """
    fuente = _fuente_canonica(fuente_id)
    limite = _validar_limite(limite, fuente)
    if confirmar_persistencia is not True:
        raise AutorizacionMetadatosError('Falta --confirmar-persistencia.')
    if fuente.identificador not in _fuentes_autorizadas():
        raise AutorizacionMetadatosError('La fuente no está autorizada para persistencia RSS de metadatos.')

    resultado = _resultado_base(fuente.identificador, limite)
    try:
        lector = lector or leer_rss
        lectura = lector(fuente, limite_entradas=limite)
        if type(lectura) is not ResultadoRSS:
            raise ValueError('El lector RSS devolvió un resultado inválido.')
    except Exception as exc:
        resultado.update(estado='ERROR', errores=1)
        resultado['causas'].append({'codigo': 'consulta_rss_fallida', 'tipo': type(exc).__name__})
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
