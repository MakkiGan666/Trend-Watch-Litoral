"""Contrato offline entre candidatos de sitemap y metadatos verificables.

No contiene transporte ni persistencia. Una coincidencia de ruta o un
``lastmod`` de sitemap no constituyen verificación editorial.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

from core.services.descarga_segura import clave_identidad_url, validar_url
from core.services.descubrimiento_historico_sitemap import PATRON_RUTA_NOTICIA
from core.services.lector_rss import NoticiaRSS


FORMATO_DESCUBRIMIENTO = 'trendwatch.historico-descubrimiento.v1'
FUENTE_ID = 'el_territorio'
MAX_TITULO = 255


class MetadatosHistoricosInvalidos(ValueError):
    """Candidato o evidencia editorial insuficiente para preparar un lote."""


@dataclass(frozen=True)
class EntradaHistoricaProcesable:
    """Metadatos compatibles con el lector RSS, con procedencia preservada."""

    noticia: NoticiaRSS
    estado_validacion: str
    procedencia: dict
    lastmod_sitemap: str | None


def _fecha_editorial(valor):
    if isinstance(valor, datetime):
        fecha = valor
    elif isinstance(valor, str) and valor.strip():
        texto = valor.strip()
        try:
            fecha = datetime.fromisoformat(texto.replace('Z', '+00:00'))
        except (TypeError, ValueError, OverflowError) as exc:
            raise MetadatosHistoricosInvalidos('fecha_publicacion_invalida') from exc
    else:
        raise MetadatosHistoricosInvalidos('fecha_publicacion_ausente')
    if fecha.tzinfo is None or fecha.utcoffset() is None:
        raise MetadatosHistoricosInvalidos('fecha_publicacion_sin_zona')
    return fecha.astimezone(timezone.utc)


def _procedencia_verificada(registro):
    procedencia = registro.get('procedencia')
    if not isinstance(procedencia, dict):
        raise MetadatosHistoricosInvalidos('procedencia_ausente')
    metodo = procedencia.get('metodo')
    titulo_origen = procedencia.get('titulo_origen')
    fecha_origen = procedencia.get('fecha_publicacion_origen')
    if not all(isinstance(v, str) and v.strip() for v in (metodo, titulo_origen, fecha_origen)):
        raise MetadatosHistoricosInvalidos('procedencia_incompleta')
    if fecha_origen.strip().lower() in {'lastmod', 'sitemap_lastmod'}:
        raise MetadatosHistoricosInvalidos('lastmod_no_es_fecha_editorial')
    # Sólo se conserva procedencia declarativa, no texto editorial adicional.
    return {
        'metodo': metodo.strip(),
        'titulo_origen': titulo_origen.strip(),
        'fecha_publicacion_origen': fecha_origen.strip(),
        **({'referencia': procedencia['referencia'].strip()}
           if isinstance(procedencia.get('referencia'), str)
           and procedencia['referencia'].strip() else {}),
    }


def adaptar_candidatas(descubrimiento, verificaciones):
    """Convierte verificaciones editoriales explícitas en entradas RSS tipadas.

    ``descubrimiento`` es la salida de ``descubrir`` y ``verificaciones`` es
    una secuencia de registros proporcionados por una futura verificación
    permitida. No confía en flags del candidato ni transforma candidatos solos.
    El resultado es una representación de datos; no crea ni inicia trabajos H5.8.
    """
    if (not isinstance(descubrimiento, dict)
            or descubrimiento.get('formato') != FORMATO_DESCUBRIMIENTO
            or descubrimiento.get('fuente_id') != FUENTE_ID
            or not isinstance(descubrimiento.get('candidatas'), list)):
        raise MetadatosHistoricosInvalidos('descubrimiento_invalido')
    if not isinstance(verificaciones, (list, tuple)):
        raise MetadatosHistoricosInvalidos('verificaciones_invalidas')

    por_url = {}
    for registro in verificaciones:
        if not isinstance(registro, dict):
            continue
        url = registro.get('url')
        try:
            validar_url(url)
            clave = clave_identidad_url(url)
        except (TypeError, ValueError):
            continue
        if clave in por_url:
            raise MetadatosHistoricosInvalidos('verificacion_duplicada')
        por_url[clave] = registro

    resultado = {'entradas': [], 'rechazadas': [], 'duplicadas': 0}
    vistas = set()
    for candidato in descubrimiento['candidatas']:
        indice = candidato.get('indice') if isinstance(candidato, dict) else None
        try:
            if not isinstance(candidato, dict):
                raise MetadatosHistoricosInvalidos('candidato_invalido')
            if (candidato.get('estado') != 'CANDIDATA_NO_VERIFICADA'
                    or candidato.get('verificada_como_noticia') is not False
                    or type(indice) is not int or indice < 0):
                raise MetadatosHistoricosInvalidos('estado_candidato_invalido')
            url = candidato.get('url')
            partes = validar_url(url)
            if not PATRON_RUTA_NOTICIA.fullmatch(partes.path):
                raise MetadatosHistoricosInvalidos('ruta_no_candidata')
            clave = clave_identidad_url(url)
            if clave in vistas:
                resultado['duplicadas'] += 1
                continue
            vistas.add(clave)
            registro = por_url.get(clave)
            if (registro is None or registro.get('estado_validacion') != 'VERIFICADA'
                    or registro.get('tipo') != 'NOTICIA'
                    or registro.get('url_verificada') is not True):
                raise MetadatosHistoricosInvalidos('url_no_verificada_como_noticia')
            titulo = registro.get('titulo')
            if not isinstance(titulo, str) or not titulo.strip() or len(titulo.strip()) > MAX_TITULO:
                raise MetadatosHistoricosInvalidos('titulo_ausente_o_invalido')
            fecha = _fecha_editorial(registro.get('fecha_publicacion'))
            procedencia = _procedencia_verificada(registro)
            noticia = NoticiaRSS(
                'El Territorio', FUENTE_ID, titulo.strip(), url, fecha,
                '', '', '',
            )
            resultado['entradas'].append(EntradaHistoricaProcesable(
                noticia=noticia,
                estado_validacion='VERIFICADA',
                procedencia={
                    'fuente_id': FUENTE_ID,
                    'url_identidad': clave,
                    'indice_descubrimiento': indice,
                    'lastmod_sitemap': candidato.get('lastmod'),
                    'verificacion': procedencia,
                },
                lastmod_sitemap=candidato.get('lastmod'),
            ))
        except MetadatosHistoricosInvalidos as exc:
            resultado['rechazadas'].append({'indice': indice, 'codigo': str(exc)})
        except (TypeError, ValueError):
            resultado['rechazadas'].append({'indice': indice, 'codigo': 'url_no_admitida'})
    return resultado
