"""Lectura H2.2 sin persistencia: sólo H2.1 descarga; feedparser procesa memoria.

Un feed malformado se rechaza completo. Entradas inválidas se informan por índice.
Fechas ausentes quedan en None; fechas presentes inválidas rechazan la entrada.
Los textos son texto plano, nunca HTML listo para renderizar.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from io import BytesIO
import re
import xml.etree.ElementTree as ET
from urllib.parse import unquote_plus

import feedparser

from core.services import descarga_segura


SEGUIMIENTO = frozenset({
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'utm_id', 'fbclid', 'gclid', 'dclid', 'msclkid', 'mc_cid', 'mc_eid',
})


@dataclass(frozen=True)
class NoticiaRSS:
    fuente: str
    fuente_id: str
    titulo: str
    url: str
    fecha: datetime | None
    resumen: str
    contenido_completo: str
    seccion: str


@dataclass(frozen=True)
class ResultadoRSS:
    noticias: tuple[NoticiaRSS, ...]
    rechazos: tuple[tuple[int, str], ...]


class _Texto(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.partes = []
        self.ocultos = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.ocultos += 1
        if not self.ocultos:
            self.partes.append(' ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.ocultos:
            self.ocultos -= 1
        if not self.ocultos:
            self.partes.append(' ')

    def handle_data(self, data):
        if not self.ocultos:
            self.partes.append(data)


TIPOS_TEXTO = frozenset({'text/plain', 'text/html', 'application/xhtml+xml'})


def _texto(valor, tipo='text/plain'):
    """Respeta texto literal; sólo elimina etiquetas en HTML/XHTML declarado."""
    if not isinstance(valor, str):
        raise ValueError('Texto inválido.')
    tipo = tipo.lower().split(';', 1)[0].strip()
    if tipo not in TIPOS_TEXTO:
        raise ValueError('Tipo de contenido textual no compatible.')
    if tipo == 'text/plain':
        return ' '.join(valor.split())
    parser = _Texto()
    parser.feed(valor)
    return ' '.join(''.join(parser.partes).split())


def _campo_texto(entrada, campo):
    detalle = entrada.get(campo + '_detail', {})
    return _texto(entrada.get(campo, ''), detalle.get('type', 'text/plain'))


def normalizar_url(url, fuente):
    """No reordena ni recodifica query, escapes o ruta; no une www/apex.

    Rechaza URLs relativas, fragmentos y hosts ajenos antes de quitar tracking.
    Sólo normaliza esquema/host y puerto HTTPS predeterminado.
    """
    partes = descarga_segura.validar_url(url, fuente=fuente)
    base = 'https://' + partes.hostname + partes.path
    if '?' not in url:
        return base
    parametros = [p for p in partes.query.split('&')
                  if unquote_plus(p.split('=', 1)[0]).lower() not in SEGUIMIENTO]
    return base + ('?' + '&'.join(parametros) if parametros else '')


def _fecha(entrada):
    # No usar *_parsed: feedparser puede completar fechas parciales o corregirlas.
    valor = entrada.get('published') if 'published' in entrada else entrada.get('updated')
    if valor is None:
        return None
    if not isinstance(valor, str) or not valor.strip():
        raise ValueError('Fecha inválida.')
    valor = valor.strip()
    try:
        offset = re.search(r'[+-](\d{2}):?(\d{2})$', valor)
        if offset and (int(offset[1]) > 23 or int(offset[2]) > 59):
            raise ValueError('Offset horario inválido.')
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})', valor):
            fecha = datetime.fromisoformat(valor.replace('Z', '+00:00'))
        elif re.fullmatch(r'(?:[A-Za-z]{3},\s+)?\d{1,2}\s+[A-Za-z]{3}\s+\d{4}\s+\d{2}:\d{2}:\d{2}\s+(?:[+-]\d{4}|GMT|UTC)', valor):
            fecha = parsedate_to_datetime(valor)
        else:
            raise ValueError('Fecha incompleta o sin zona horaria.')
        return fecha.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise ValueError('Fecha inválida.') from exc


def _normalizar(entrada, fuente, tiene_resumen, nodo):
    titulo = _campo_texto(entrada, 'title')
    if not titulo or len(titulo) > 255:
        raise ValueError('Título vacío o mayor a 255 caracteres.')
    url = normalizar_url(entrada.get('link'), fuente)
    if len(url) > 500:
        raise ValueError('URL mayor a 500 caracteres.')
    contenidos = entrada.get('content', [])
    # Atom content src no se descarga ni se presenta como contenido completo.
    for hijo in nodo:
        if hijo.tag in ('{http://www.w3.org/2005/Atom}content',
                        '{http://purl.org/rss/1.0/modules/content/}encoded'):
            if hijo.get('mode', '').lower() == 'base64' or hijo.get('encoding'):
                raise ValueError('Contenido codificado no compatible con un artículo.')
    contenido = '\n\n'.join(_texto(c.get('value', ''), c.get('type', 'text/plain'))
                             for c in contenidos if not c.get('src'))
    # feedparser copia content a summary; sólo conservar resúmenes explícitos.
    resumen = _campo_texto(entrada, 'summary') if tiene_resumen else ''
    etiquetas = entrada.get('tags', [])
    seccion = next((_texto(t.get('term', '')) for t in etiquetas if t.get('term')), '')
    return NoticiaRSS(fuente.nombre, fuente.identificador, titulo, url,
                      _fecha(entrada), resumen, contenido, seccion)


class _XMLSinDTD(ET.TreeBuilder):
    def doctype(self, name, pubid, system):
        raise ValueError('DTD y entidades no permitidos en feeds.')


def _limite_entradas(fuente, limite_entradas):
    if limite_entradas is None:
        return fuente.limite_noticias
    if type(limite_entradas) is not int or limite_entradas < 1:
        raise ValueError('El límite de entradas debe ser un entero positivo.')
    return min(limite_entradas, fuente.limite_noticias)


def analizar_rss(datos, fuente, *, limite_entradas=None):
    """Procesa bytes ya descargados, con la política canónica y su límite."""
    descarga_segura.validar_url(fuente.feed, fuente=fuente)
    limite = _limite_entradas(fuente, limite_entradas)
    if not isinstance(datos, bytes) or len(datos) > fuente.max_bytes:
        raise ValueError('Feed inválido o demasiado grande.')
    try:
        raiz = ET.fromstring(datos, parser=ET.XMLParser(target=_XMLSinDTD()))
    except ET.ParseError as exc:
        raise ValueError('Feed XML malformado.') from exc
    # Sólo estos formatos tienen una correspondencia inequívoca por entrada.
    rss1 = '{http://purl.org/rss/1.0/}'
    atom = '{http://www.w3.org/2005/Atom}'
    if raiz.tag == 'rss':
        nodos = raiz.findall('./channel/item')
        campo_resumen = 'description'
    elif raiz.tag == '{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF':
        nodos = raiz.findall(rss1 + 'item')
        campo_resumen = rss1 + 'description'
    elif raiz.tag == atom + 'feed':
        nodos = raiz.findall(atom + 'entry')
        campo_resumen = atom + 'summary'
    else:
        raise ValueError('Formato de feed no admitido.')
    feed = feedparser.parse(BytesIO(datos), resolve_relative_uris=False, sanitize_html=True)
    if feed.get('bozo') or not feed.get('version') or len(nodos) != len(feed.entries):
        raise ValueError('Feed malformado o formato no reconocido.')
    noticias, rechazos = [], []
    for indice, entrada in enumerate(feed.entries[:limite]):
        try:
            noticias.append(_normalizar(entrada, fuente, nodos[indice].find(campo_resumen) is not None, nodos[indice]))
        except (ValueError, TypeError, AttributeError) as exc:
            rechazos.append((indice, str(exc)))
    return ResultadoRSS(tuple(noticias), tuple(rechazos))


def leer_rss(fuente, *, limite_entradas=None):
    """Una sola descarga mediante H2.1; no extrae artículos ni contenido externo."""
    descarga_segura.validar_url(fuente.feed, fuente=fuente)
    limite = _limite_entradas(fuente, limite_entradas)
    datos = descarga_segura.descargar(fuente.feed, fuente=fuente)
    return analizar_rss(datos, fuente, limite_entradas=limite)
