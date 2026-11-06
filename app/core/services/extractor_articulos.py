"""H2.3: extracción local, sin navegador, persistencia ni descargas secundarias.

Las URLs de imágenes usan la misma política de hosts HTTPS que el artículo;
CDN ajenos no se autorizan implícitamente. Nunca se siguen canonical, base,
iframes, imágenes, scripts ni contextos JSON-LD. El cuerpo es texto plano.
"""
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
import json
import re
from urllib.parse import urljoin, urlsplit

from core.services import descarga_segura
from core.services.fuentes_rss import FUENTES_RSS
from core.services.lector_rss import NoticiaRSS, _fecha, normalizar_url


class ErrorExtraccion(ValueError):
    """Fallo de extracción con código y métricas sanitizadas, compatible con ValueError."""

    def __init__(self, codigo, mensaje, metricas=None):
        super().__init__(mensaje)
        self.codigo = codigo
        self.metricas = dict(metricas or {})


def _error(codigo, mensaje, metricas):
    return ErrorExtraccion(codigo, mensaje, metricas)


def _metricas_iniciales(noticia):
    try:
        hostname = urlsplit(noticia.url).hostname
    except (AttributeError, TypeError, ValueError):
        hostname = None
    return {
        'hostname': hostname,
        'charset': None,
        'nodos_html': 0,
        'scripts_jsonld': 0,
        'candidatos_jsonld': 0,
        'jsonld_invalidos': 0,
        'canonicas_invalidas': 0,
        'longitudes_contenedores': [],
    }


@dataclass(frozen=True)
class ArticuloExtraido:
    fuente: str
    fuente_id: str
    titulo: str
    cuerpo: str
    imagen_principal: str
    fecha: datetime | None
    url_canonica: str
    suficiente: bool


@dataclass
class _Nodo:
    tag: str
    attrs: dict
    hijos: list = field(default_factory=list)
    contexto_excluido: bool = False


_VACIOS = frozenset({'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
                     'link', 'meta', 'param', 'source', 'track', 'wbr'})
_EXCLUIR = frozenset({'nav', 'aside', 'header', 'footer', 'script', 'style',
                       'noscript', 'form', 'button', 'iframe', 'template', 'svg'})
_RUIDO = re.compile(r'(?:^|[-_\s])(?:ad|ads|advertisement|advertising|publicidad|banner|'
                    r'related|relacionados|relacionadas|recommended|recomendadas|'
                    r'share|sharing|social|menu|sidebar|newsletter|comments|comentarios|'
                    r'cookie|cookies)(?:$|[-_\s])', re.I)
_CONTENEDORES = frozenset({'entry-content', 'article-content', 'article-body',
                           'news-content', 'post-content', 'nota-contenido',
                           'cuerpo-noticia', 'td-post-content'})


class _Documento(HTMLParser):
    """Árbol acotado; no usa parsers con resolución de entidades o recursos."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.raiz = _Nodo('document', {})
        self.pila = [self.raiz]
        self.nodos = []

    def handle_starttag(self, tag, attrs):
        if len(self.nodos) >= 30000 or len(self.pila) >= 128:
            raise ValueError('HTML demasiado complejo.')
        padre = self.pila[-1]
        nodo = _Nodo(tag, dict(attrs), contexto_excluido=(
            padre.contexto_excluido or _ruido(padre, cabeceras=True)))
        self.pila[-1].hijos.append(nodo)
        self.nodos.append(nodo)
        if tag not in _VACIOS:
            self.pila.append(nodo)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VACIOS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for indice in range(len(self.pila) - 1, 0, -1):
            if self.pila[indice].tag == tag:
                del self.pila[indice:]
                break

    def handle_data(self, texto):
        self.pila[-1].hijos.append(texto)


def _limpiar(texto):
    return ' '.join(texto.split()) if isinstance(texto, str) else ''


def _ruido(nodo, cabeceras=False, scripts=False):
    attrs = nodo.attrs
    return ((nodo.tag in _EXCLUIR and not (cabeceras and nodo.tag == 'header')
             and not (scripts and nodo.tag == 'script')) or 'hidden' in attrs
            or (attrs.get('aria-hidden') or '').lower() == 'true'
            or bool(re.search(r'(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)\s*(?:!important\s*)?(?:;|$)',
                              attrs.get('style') or '', re.I))
            or attrs.get('role') in ('navigation', 'banner', 'complementary')
            or bool(_RUIDO.search((attrs.get('class') or '') + ' ' + (attrs.get('id') or ''))))


def _texto(nodo, limpio=True):
    if isinstance(nodo, str):
        return nodo
    if limpio and _ruido(nodo):
        return ''
    return ' '.join(_texto(hijo, limpio) for hijo in nodo.hijos)


def _recorrer(nodo, cabeceras=False):
    for hijo in nodo.hijos:
        if isinstance(hijo, _Nodo) and not _ruido(hijo, cabeceras):
            yield hijo
            yield from _recorrer(hijo, cabeceras)


def _bloques_parrafo(nodo):
    for hijo in nodo.hijos:
        if not isinstance(hijo, _Nodo) or _ruido(hijo):
            continue
        if hijo.tag in ('p', 'h2', 'h3', 'blockquote'):
            yield hijo  # Consumir el bloque completo, sin emitir sus hijos otra vez.
        else:
            yield from _bloques_parrafo(hijo)


def _parrafos(nodo):
    partes = []
    for hijo in _bloques_parrafo(nodo):
        texto = _limpiar(_texto(hijo))
        enlaces = sum(len(_limpiar(_texto(n))) for n in _recorrer(hijo) if n.tag == 'a')
        if texto and enlaces <= len(texto) * 0.5:
            partes.append(texto)
    return _deduplicar(partes)


def _deduplicar(partes):
    vistos, salida = set(), []
    for parte in partes:
        parte = _limpiar(parte)
        clave = parte.casefold()
        if parte and clave not in vistos:
            vistos.add(clave)
            salida.append(parte)
    return '\n\n'.join(salida)


def _suficiente(cuerpo):
    return len(cuerpo) >= 120 and len(cuerpo.split()) >= 20


def _titulo(valor):
    valor = _limpiar(valor)
    return valor if valor and len(valor) <= 255 else ''


def _url(valor, base, fuente):
    if not isinstance(valor, str) or not valor:
        return ''
    # Validar antes de urljoin: éste elimina controles iniciales silenciosamente.
    if '\\' in valor or any(ord(c) <= 32 or ord(c) == 127 for c in valor):
        return ''
    try:
        url = normalizar_url(urljoin(base, valor), fuente)
    except ValueError:
        return ''
    return url if len(url) <= 500 else ''


def _fecha_valida(valor):
    try:
        return _fecha({'published': valor}) if valor else None
    except (ValueError, TypeError):
        return None


def _json_articulos(documento):
    articulos = []
    for nodo in documento.nodos:
        if (nodo.contexto_excluido or _ruido(nodo, cabeceras=True, scripts=True)
                or nodo.attrs.get('src')):
            continue
        if nodo.tag != 'script' or (nodo.attrs.get('type') or '').lower() != 'application/ld+json':
            continue
        try:
            datos = json.loads(_texto(nodo, limpio=False))
        except (ValueError, RecursionError):
            continue
        # Sólo raíces y @graph, nunca artículos de itemList/relatedLink.
        pendientes = datos if isinstance(datos, list) else [datos]
        for dato in pendientes:
            if not isinstance(dato, dict):
                continue
            grafo = dato.get('@graph')
            candidatos = grafo if isinstance(grafo, list) else [dato]
            for candidato in candidatos:
                if not isinstance(candidato, dict):
                    continue
                tipos = candidato.get('@type', [])
                tipos = [tipos] if isinstance(tipos, str) else tipos
                if isinstance(tipos, list) and any(t in ('Article', 'NewsArticle', 'https://schema.org/Article',
                                                        'https://schema.org/NewsArticle') for t in tipos):
                    articulos.append(candidato)
    return articulos


def _identidades_json(articulo):
    for campo in ('mainEntityOfPage', 'url'):
        valor = articulo.get(campo)
        if valor:
            yield valor.get('@id') if isinstance(valor, dict) else valor


def _rechazar_host_ajeno(identidad, base, fuente, metricas, *, canonical=False):
    if not isinstance(identidad, str):
        return
    try:
        host = urlsplit(urljoin(base, identidad)).hostname
    except ValueError:
        return
    if host:
        metricas['hostname_declarado'] = host
    if host and host not in fuente.hosts_permitidos:
        codigo = 'URL_CANONICA' if canonical else 'IDENTIDAD_EDITORIAL'
        raise _error(codigo, 'El HTML declara un host no autorizado.', metricas)


def _imagen_json(valor):
    if isinstance(valor, list):
        return [_imagen_json(v) for v in valor]
    if isinstance(valor, dict):
        return valor.get('url') or valor.get('contentUrl')
    return valor


def _candidatos_imagen(valor):
    if isinstance(valor, list):
        for item in valor:
            yield from _candidatos_imagen(item)
    elif isinstance(valor, str):
        yield valor


def _validar_noticia(noticia, fuente):
    descarga_segura.validar_url(fuente.feed, fuente=fuente)
    if (type(noticia) is not NoticiaRSS or noticia.fuente_id != fuente.identificador
            or noticia.fuente != fuente.nombre or not _titulo(noticia.titulo)):
        raise ValueError('Noticia RSS incompatible con la fuente.')
    descarga_segura.validar_url(noticia.url, fuente=fuente)
    if noticia.fecha is not None and (not isinstance(noticia.fecha, datetime)
                                      or noticia.fecha.tzinfo is None
                                      or noticia.fecha.utcoffset() is None):
        raise ValueError('Fecha RSS inválida.')


def analizar_articulo(datos, noticia, fuente, *, _metricas=None):
    """Analiza HTML acotado. Una identidad editorial ajena rechaza la página."""
    metricas = _metricas if _metricas is not None else _metricas_iniciales(noticia)
    try:
        _validar_noticia(noticia, fuente)
    except (ValueError, AttributeError, TypeError) as exc:
        raise _error('IDENTIDAD_EDITORIAL', 'Noticia o fuente incompatible.', metricas) from exc
    if not isinstance(datos, bytes):
        raise _error('HTML_INVALIDO', 'HTML inválido.', metricas)
    if len(datos) > fuente.max_bytes:
        raise _error('LIMITE_PROCESAMIENTO', 'HTML supera el límite de tamaño.', metricas)
    documento = _Documento()
    # HTMLParser no infiere codificaciones; UTF-8 y charset declarado son comunes.
    charset = re.search(br'<meta\b[^>]*charset\s*=\s*["\x27]?\s*([a-zA-Z0-9_-]+)', datos[:8192], re.I)
    codificacion = charset[1].decode('ascii') if charset else 'utf-8'
    metricas['charset'] = codificacion.lower()
    if codificacion.lower() not in ('utf-8', 'utf8', 'iso-8859-1', 'latin-1', 'windows-1252'):
        raise _error('CODIFICACION', 'Codificación HTML no admitida.', metricas)
    try:
        documento.feed(datos.decode(codificacion))
        documento.close()
    except (UnicodeError, LookupError) as exc:
        raise _error('CODIFICACION', 'Codificación HTML inválida.', metricas) from exc
    except ValueError as exc:
        metricas['nodos_html'] = len(documento.nodos)
        metricas['scripts_jsonld'] = sum(
            nodo.tag == 'script' and (nodo.attrs.get('type') or '').lower() == 'application/ld+json'
            for nodo in documento.nodos
        )
        codigo = 'LIMITE_PROCESAMIENTO' if 'complejo' in str(exc).lower() else 'HTML_INVALIDO'
        raise _error(codigo, 'No se pudo procesar el HTML.', metricas) from exc
    metricas['nodos_html'] = len(documento.nodos)
    metadatos = {}
    canonicas = []
    for nodo in documento.nodos:
        if nodo.tag == 'meta':
            clave = nodo.attrs.get('property') or nodo.attrs.get('name')
            if isinstance(clave, str):
                metadatos.setdefault(clave.lower(), []).append(nodo.attrs.get('content'))
        if nodo.tag == 'link' and 'canonical' in (nodo.attrs.get('rel') or '').lower().split():
            canonicas.append(nodo.attrs.get('href'))
    identidades = canonicas + metadatos.get('og:url', [])
    metricas['canonicas_invalidas'] = sum(
        bool(v) and not _url(v, noticia.url, fuente) for v in canonicas
    )
    url = next((u for v in identidades if (u := _url(v, noticia.url, fuente))), noticia.url)
    articulos = _json_articulos(documento)
    metricas['scripts_jsonld'] = sum(
        nodo.tag == 'script' and (nodo.attrs.get('type') or '').lower() == 'application/ld+json'
        for nodo in documento.nodos
    )
    metricas['candidatos_jsonld'] = len(articulos)
    metricas['jsonld_invalidos'] = sum(
        nodo.tag == 'script' and (nodo.attrs.get('type') or '').lower() == 'application/ld+json'
        and not _json_script_valido(nodo) for nodo in documento.nodos
    )
    visibles = list(_recorrer(documento.raiz))
    contenedores = [n for n in visibles if not _ruido(n) and (
        n.attrs.get('itemprop') == 'articleBody'
        or bool(set((n.attrs.get('class') or '').split()) & _CONTENEDORES))]
    if not contenedores:
        contenedores = [n for n in visibles if n.tag == 'article' and not _ruido(n)]
    # Fallback: un solo main; nunca todo body o el texto de la página.
    if not contenedores:
        principales = [n for n in visibles if n.tag == 'main' and not _ruido(n)]
        contenedores = principales if len(principales) == 1 else []
    metricas['longitudes_contenedores'] = [
        {'indice': indice, 'elemento': nodo.tag,
         'caracteres': len(texto := _parrafos(nodo)),
         'palabras': len(texto.split())}
        for indice, nodo in enumerate(contenedores[:50])
    ]
    for identidad in canonicas:
        _rechazar_host_ajeno(identidad, noticia.url, fuente, metricas, canonical=True)
    for identidad in metadatos.get('og:url', []):
        _rechazar_host_ajeno(identidad, noticia.url, fuente, metricas)
    elegibles = []
    for articulo in articulos:
        identidades_articulo = list(_identidades_json(articulo))
        for identidad in identidades_articulo:
            _rechazar_host_ajeno(identidad, noticia.url, fuente, metricas)
        if any(_url(identidad, noticia.url, fuente) not in (
            normalizar_url(noticia.url, fuente), normalizar_url(url, fuente)
        ) for identidad in identidades_articulo):
            continue
        elegibles.append(articulo)
    articulo = elegibles[0] if len(elegibles) == 1 else {}
    if articulos and not elegibles:
        raise _error('JSONLD', 'JSON-LD no contiene un artículo asociado.', metricas)

    def meta(clave):
        return metadatos.get(clave, [])

    candidatos_titulo = [articulo.get('headline'), *meta('og:title')]
    contenedor = max(contenedores, key=lambda n: len(_parrafos(n)), default=None)
    if contenedor is not None:
        entorno = next((n for n in visibles if n.tag == 'article' and (
            n is contenedor or any(hijo is contenedor for hijo in _recorrer(n)))), contenedor)
        candidatos_titulo += [_texto(n) for n in _recorrer(entorno, cabeceras=True) if n.tag == 'h1']
    titulo = next((t for v in candidatos_titulo if (t := _titulo(v))), noticia.titulo)
    cuerpo_json = articulo.get('articleBody')
    cuerpo = _deduplicar(cuerpo_json.splitlines()) if isinstance(cuerpo_json, str) else ''
    if not _suficiente(cuerpo) and contenedor is not None:
        cuerpo_html = _parrafos(contenedor)
        if _suficiente(cuerpo_html) or len(cuerpo_html) > len(cuerpo):
            cuerpo = cuerpo_html
    fechas = [articulo.get('datePublished'), *meta('article:published_time'),
              *meta('datePublished')]
    if contenedor is not None:
        fechas += [n.attrs.get('datetime') for n in _recorrer(contenedor)
                   if n.tag == 'time' and n.attrs.get('itemprop') != 'dateModified']
    fecha = next((f for v in fechas if (f := _fecha_valida(v))), noticia.fecha)
    imagenes = list(_candidatos_imagen(_imagen_json(articulo.get('image')))) + meta('og:image')
    if contenedor is not None:
        imagenes += [n.attrs.get('src') or n.attrs.get('data-src') for n in _recorrer(contenedor)
                     if n.tag == 'img']
    imagen = next((u for v in imagenes if (u := _url(v, noticia.url, fuente))), '')
    suficiente = _suficiente(cuerpo)
    return ArticuloExtraido(fuente.nombre, fuente.identificador, titulo, cuerpo, imagen,
                           fecha, url, suficiente)


def _json_script_valido(nodo):
    try:
        json.loads(_texto(nodo, limpio=False))
        return True
    except (ValueError, RecursionError):
        return False


def diagnosticar_articulo(datos, noticia, fuente):
    """Devuelve sólo métricas y banderas; nunca incluye título, cuerpo ni URL."""
    metricas = _metricas_iniciales(noticia)
    try:
        articulo = analizar_articulo(datos, noticia, fuente, _metricas=metricas)
    except ErrorExtraccion as exc:
        return {'estado': 'error', 'codigo': exc.codigo, 'metricas': exc.metricas}
    return {
        'estado': 'analizado', 'codigo': None,
        'metricas': metricas,
        'titulo_presente': bool(articulo.titulo),
        'fecha_presente': articulo.fecha is not None,
        'cuerpo_caracteres': len(articulo.cuerpo),
        'cuerpo_palabras': len(articulo.cuerpo.split()),
        'suficiente': articulo.suficiente,
        'imagen_presente': bool(articulo.imagen_principal),
        'canonica_valida': True,
        'identidad_coincidente': articulo.fuente_id == fuente.identificador,
    }


def extraer_articulo(noticia, fuente=None):
    """Recibe NoticiaRSS H2.2 y hace una única descarga HTML mediante H2.1."""
    if fuente is None:
        fuente = next((f for f in FUENTES_RSS if f.identificador == noticia.fuente_id), None)
    if fuente is None:
        raise ValueError('Fuente RSS desconocida.')
    _validar_noticia(noticia, fuente)
    datos = descarga_segura.descargar(noticia.url, fuente=fuente)
    return analizar_articulo(datos, noticia, fuente)
