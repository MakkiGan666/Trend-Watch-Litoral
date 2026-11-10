"""Descubrimiento offline y acotado de URLs en XML Sitemap de El Territorio.

Este módulo sólo analiza bytes suministrados por quien lo invoca. No tiene
transporte HTTP, persistencia ni lógica para verificar que una URL sea noticia.
"""
from __future__ import annotations

from datetime import date, datetime
import json
import re
import xml.etree.ElementTree as ET

from core.services.descarga_segura import clave_identidad_url, validar_url


FUENTE_ID = 'el_territorio'
NS_SITEMAP = 'http://www.sitemaps.org/schemas/sitemap/0.9'
MAX_XML_BYTES = 2_000_000
MAX_ELEMENTOS = 100
MAX_URL_CHARS = 500
PATRON_RUTA_NOTICIA = re.compile(r'^/noticias/\d{4}/\d{2}/\d{2}/\d+-[^/?#]+/?$')
_DECLARACION_ENTIDAD = re.compile(br'<!\s*(?:DOCTYPE|ENTITY)\b', re.IGNORECASE)


class SitemapInvalido(ValueError):
    """Documento XML no admitido, demasiado grande o malformado."""


def _bytes_xml(documento: bytes | str) -> bytes:
    if isinstance(documento, str):
        try:
            contenido = documento.encode('utf-8')
        except UnicodeEncodeError as exc:
            raise SitemapInvalido('xml_encoding_invalido') from exc
    elif isinstance(documento, bytes):
        contenido = documento
    else:
        raise SitemapInvalido('xml_tipo_invalido')
    if not contenido or len(contenido) > MAX_XML_BYTES:
        raise SitemapInvalido('xml_tamano_invalido')
    if _DECLARACION_ENTIDAD.search(contenido):
        raise SitemapInvalido('xml_dtd_no_admitido')
    return contenido


def _nombre_local(elemento: ET.Element) -> tuple[str, str]:
    tag = elemento.tag
    if not isinstance(tag, str):
        return '', ''
    if tag.startswith('{') and '}' in tag:
        namespace, local = tag[1:].split('}', 1)
        return namespace, local
    return '', tag


def _raiz(documento: bytes | str) -> tuple[str, str, list[ET.Element]]:
    contenido = _bytes_xml(documento)
    try:
        raiz = ET.fromstring(contenido)
    except (ET.ParseError, ValueError, RecursionError) as exc:
        raise SitemapInvalido('xml_malformado') from exc
    namespace, tipo = _nombre_local(raiz)
    if namespace not in ('', NS_SITEMAP) or tipo not in ('sitemapindex', 'urlset'):
        raise SitemapInvalido('raiz_sitemap_no_admitida')
    elementos = []
    for hijo in raiz:
        ns_hijo, nombre = _nombre_local(hijo)
        if ns_hijo == namespace and nombre in (('sitemap',) if tipo == 'sitemapindex' else ('url',)):
            elementos.append(hijo)
    return tipo, namespace, elementos


def _limite(limite: int) -> int:
    if type(limite) is not int or not 1 <= limite <= MAX_ELEMENTOS:
        raise ValueError(f'limite debe ser un entero entre 1 y {MAX_ELEMENTOS}.')
    return limite


def _campos(elemento: ET.Element, namespace: str) -> tuple[str, str | None]:
    url = ''
    lastmod = None
    for hijo in elemento:
        ns_hijo, nombre = _nombre_local(hijo)
        if ns_hijo != namespace:
            continue
        texto = hijo.text.strip() if hijo.text else ''
        if nombre == 'loc' and not url:
            url = texto
        elif nombre == 'lastmod' and lastmod is None:
            lastmod = texto or None
    return url, lastmod


def _estado_lastmod(valor: str | None) -> str:
    if valor is None:
        return 'AUSENTE'
    if len(valor) > 64:
        return 'INVALIDO'
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', valor):
            date.fromisoformat(valor)
        else:
            datetime.fromisoformat(valor.replace('Z', '+00:00'))
    except (TypeError, ValueError, OverflowError):
        return 'INVALIDO'
    return 'VALIDO'


def _url_admitida(url: str) -> tuple[str | None, str | None]:
    if not url:
        return None, 'loc_ausente'
    if len(url) > MAX_URL_CHARS:
        return None, 'url_demasiado_larga'
    try:
        validar_url(url)
        return clave_identidad_url(url), None
    except (TypeError, ValueError):
        return None, 'url_no_admitida'


def descubrir(documento: bytes | str, *, limite: int = 20) -> dict:
    """Analiza un sitemap local; nunca hace GET ni verifica páginas de artículos.

    En un `sitemapindex` devuelve referencias anidadas pendientes, sin seguirlas.
    En un `urlset` sólo considera candidatas las rutas que coinciden con el patrón
    de noticias conocido por el parser legacy de El Territorio. Aun así, cada una
    conserva `verificada_como_noticia=False` y no recibe fecha de publicación.
    """
    limite = _limite(limite)
    tipo, namespace, elementos = _raiz(documento)
    resultado = {
        'formato': 'trendwatch.historico-descubrimiento.v1',
        'fuente_id': FUENTE_ID,
        'tipo_documento': tipo,
        'limite': limite,
        'candidatas': [],
        'sitemaps_pendientes': [],
        'no_candidatas': [],
        'rechazadas': [],
        'duplicadas': 0,
        'fuera_limite': 0,
    }
    vistos = set()
    salida = resultado['sitemaps_pendientes'] if tipo == 'sitemapindex' else resultado['candidatas']

    for indice, elemento in enumerate(elementos):
        url, lastmod = _campos(elemento, namespace)
        clave, error = _url_admitida(url)
        if error:
            resultado['rechazadas'].append({'indice': indice, 'codigo': error})
            continue
        if clave in vistos:
            resultado['duplicadas'] += 1
            continue
        vistos.add(clave)
        partes = validar_url(url)

        if tipo == 'urlset':
            es_ruta_candidata = bool(PATRON_RUTA_NOTICIA.fullmatch(partes.path))
            if not es_ruta_candidata:
                resultado['no_candidatas'].append({
                    'indice': indice,
                    'url': url,
                    'codigo': 'ruta_no_reconocida',
                })
                continue

        if len(salida) >= limite:
            resultado['fuera_limite'] += 1
            continue

        item = {
            'indice': indice,
            'url': url,
            'lastmod': lastmod if _estado_lastmod(lastmod) == 'VALIDO' else None,
            'lastmod_estado': _estado_lastmod(lastmod),
        }
        if tipo == 'sitemapindex':
            item.update({'estado': 'SITEMAP_PENDIENTE', 'descarga_automatica': False})
        else:
            item.update({
                'estado': 'CANDIDATA_NO_VERIFICADA',
                'verificada_como_noticia': False,
                'fecha_publicacion': None,
            })
        salida.append(item)
    return resultado


def a_json(resultado: dict) -> str:
    """Serializa el resultado sin agregar datos editoriales."""
    return json.dumps(resultado, ensure_ascii=False, sort_keys=True)
