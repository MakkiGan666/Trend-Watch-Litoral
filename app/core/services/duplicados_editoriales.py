"""Candidatos conservadores a duplicado editorial; nunca altera publicaciones."""

from collections import defaultdict
from datetime import date, datetime
from difflib import SequenceMatcher
from html import unescape
import re
import unicodedata
from urllib.parse import unquote_plus, urlsplit


_SECCIONES_TERRITORIO = frozenset({
    'archivo', 'misiones', 'tecnologia', 'policiales', 'cultura', 'actualidad',
    'deportes', 'agro', 'la region', 'pais y mundo',
})
_TRACKING = frozenset({
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'utm_id', 'fbclid', 'gclid', 'dclid', 'msclkid', 'mc_cid', 'mc_eid',
})
_LONGITUD_MINIMA_CONTENIDO = 300


def normalizar_texto(valor):
    """Plegado determinista de tildes, caja, puntuación y espacios."""
    texto = unicodedata.normalize('NFKD', str(valor or '').casefold())
    texto = ''.join(caracter for caracter in texto if not unicodedata.category(caracter).startswith('M'))
    return ' '.join(re.findall(r'[^\W_]+', texto, flags=re.UNICODE))


def normalizar_fuente(fuente):
    """Unifica secciones conocidas de El Territorio; conserva otros medios."""
    nombre = normalizar_texto(fuente)
    prefijo = 'el territorio '
    if nombre == 'el territorio':
        return nombre
    if nombre.startswith(prefijo) and nombre[len(prefijo):] in _SECCIONES_TERRITORIO:
        return 'el territorio'
    return nombre


def canonicalizar_url(url):
    """Canonización limitada: host/esquema/default port, fragmento y tracking.

    Conserva path, barra final y parámetros funcionales. No hace HTTP ni
    intenta inferir redirecciones o canonical tags.
    """
    if not isinstance(url, str) or not url.strip():
        return ''
    try:
        partes = urlsplit(url.strip())
        host = partes.hostname
        puerto = partes.port
    except ValueError:
        return ''
    esquema = partes.scheme.casefold()
    if esquema not in {'http', 'https'} or not host or partes.username or partes.password:
        return ''
    host = host.casefold().rstrip('.')
    if host.startswith('www.'):
        host = host[4:]
    if puerto and puerto not in ({80} if esquema == 'http' else {443}):
        host = f'{host}:{puerto}'
    ruta = partes.path or '/'
    segmentos = []
    for segmento in partes.query.split('&') if partes.query else ():
        clave = unquote_plus(segmento.split('=', 1)[0]).casefold()
        if clave in _TRACKING or clave.startswith('utm_'):
            continue
        segmentos.append(segmento)
    consulta = '&'.join(segmentos)
    return f'https://{host}{ruta}' + (f'?{consulta}' if consulta else '')


def _fecha(valor):
    """Sólo fecha editorial; nunca sustituye por fecha de captura."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, str) and valor.strip():
        texto = valor.strip()
        try:
            return datetime.fromisoformat(texto.replace('Z', '+00:00')).date()
        except ValueError:
            try:
                return date.fromisoformat(texto[:10])
            except ValueError:
                return None
    return None


def _contenido(valor):
    texto = unescape(str(valor or ''))
    texto = re.sub(r'<[^>]*>', ' ', texto)
    return normalizar_texto(texto)


def _similitud(a, b):
    if not a or not b:
        return None
    secuencia = SequenceMatcher(None, a, b, autojunk=True).ratio()
    tokens_a, tokens_b = set(a.split()), set(b.split())
    union = tokens_a | tokens_b
    jaccard = len(tokens_a & tokens_b) / len(union) if union else 0.0
    return round((secuencia + jaccard) / 2, 4)


def _preparar(registros):
    preparados = []
    for registro in registros:
        fila = dict(registro)
        fila['pk'] = fila.get('pk', fila.get('id'))
        fila['fuente_original'] = str(fila.get('fuente') or '')
        fila['fuente_key'] = normalizar_fuente(fila['fuente_original'])
        fila['titulo'] = str(fila.get('titulo') or '')
        fila['titulo_key'] = normalizar_texto(fila['titulo'])
        fila['url'] = str(fila.get('url') or '')
        fila['url_key'] = canonicalizar_url(fila['url'])
        fila['fecha'] = _fecha(fila.get('fecha_publicacion'))
        fila['completa'] = fila.get('contenido_completo') is True
        fila['contenido_key'] = _contenido(fila.get('contenido')) if fila['completa'] else ''
        preparados.append(fila)
    return sorted(preparados, key=lambda f: (str(f.get('pk') or ''), f['fuente_key'], f['url_key']))


def _pares_candidatos(filas):
    pares = set()
    por_url, por_titulo_fuente, por_titulo = defaultdict(list), defaultdict(list), defaultdict(list)
    por_fecha = defaultdict(list)
    for indice, fila in enumerate(filas):
        if fila['url_key']:
            por_url[(fila['fuente_key'], fila['url_key'])].append(indice)
        if fila['titulo_key']:
            por_titulo_fuente[(fila['fuente_key'], fila['titulo_key'])].append(indice)
            por_titulo[fila['titulo_key']].append(indice)
        if fila['fecha']:
            por_fecha[fila['fecha']].append(indice)

    def agregar(indices):
        for i, primero in enumerate(indices):
            for segundo in indices[i + 1:]:
                pk_primero, pk_segundo = filas[primero]['pk'], filas[segundo]['pk']
                if pk_primero is None or pk_segundo is None or pk_primero != pk_segundo:
                    pares.add((min(primero, segundo), max(primero, segundo)))

    for grupo in por_url.values():
        agregar(grupo)
    for grupo in por_titulo_fuente.values():
        agregar(grupo)
    for grupo in por_titulo.values():
        agregar(grupo)

    dias = sorted(por_fecha)
    for dia in dias:
        actuales = por_fecha[dia]
        # También comparar dentro del mismo día: los titulares repetidos o
        # reformulados suelen corresponder a actualizaciones de una misma nota.
        for primero_pos, primero in enumerate(actuales):
            for segundo in actuales[primero_pos + 1:]:
                a, b = filas[primero], filas[segundo]
                umbral = 0.78 if a['fuente_key'] == b['fuente_key'] else 0.90
                if SequenceMatcher(None, a['titulo_key'], b['titulo_key']).ratio() >= umbral:
                    pares.add((min(primero, segundo), max(primero, segundo)))
        for delta in (1, 2):
            siguientes = por_fecha.get(date.fromordinal(dia.toordinal() + delta), ())
            for primero in actuales:
                for segundo in siguientes:
                    a, b = filas[primero], filas[segundo]
                    if a['fuente_key'] == b['fuente_key']:
                        umbral = 0.78
                    else:
                        umbral = 0.90
                    if SequenceMatcher(None, a['titulo_key'], b['titulo_key']).ratio() >= umbral:
                        pares.add((min(primero, segundo), max(primero, segundo)))
    return sorted(pares)


def _evaluar(a, b):
    misma_fuente = a['fuente_key'] == b['fuente_key']
    url_igual = bool(a['url_key'] and a['url_key'] == b['url_key'])
    similitud_titulo = round(SequenceMatcher(None, a['titulo_key'], b['titulo_key']).ratio(), 4)
    similitud_cuerpo = None
    if (a['completa'] and b['completa']
            and min(len(a['contenido_key']), len(b['contenido_key'])) >= _LONGITUD_MINIMA_CONTENIDO):
        similitud_cuerpo = _similitud(a['contenido_key'], b['contenido_key'])
    dias = abs((a['fecha'] - b['fecha']).days) if a['fecha'] and b['fecha'] else None
    misma_fecha_cercana = dias is not None and dias <= 2

    if not misma_fuente:
        estado = 'COBERTURA_MULTIMEDIO' if misma_fecha_cercana and similitud_titulo >= 0.80 else 'TITULO_COINCIDENTE_ENTRE_FUENTES'
        razon = 'Se preserva la procedencia: coincidencia entre medios no fusiona publicaciones.'
    elif url_igual:
        estado = 'DUPLICADO_CONFIRMADO'
        razon = 'Misma URL canonicalizada dentro de la misma fuente.'
    elif (similitud_cuerpo is not None and dias is not None and dias <= 1
          and similitud_titulo >= 0.70 and similitud_cuerpo >= 0.94):
        estado = 'DUPLICADO_CONFIRMADO'
        razon = 'Misma fuente, fecha cercana, título relacionado y cuerpo casi idéntico.'
    elif (similitud_cuerpo is not None and dias is not None and dias <= 2
          and similitud_titulo >= 0.80 and similitud_cuerpo >= 0.78):
        estado = 'DUPLICADO_PROBABLE'
        razon = 'Misma fuente, título y fecha relacionados, con similitud editorial sustancial.'
    elif (not a['completa'] or not b['completa']) and similitud_titulo >= 0.80 and misma_fecha_cercana:
        estado = 'DATOS_INSUFICIENTES'
        razon = 'Hay ficha RSS o falta cuerpo; título y fecha no bastan para afirmar duplicación.'
    elif similitud_titulo >= 0.80 and misma_fecha_cercana and similitud_cuerpo is not None:
        estado = 'TITULO_COINCIDENTE_DISTINTO_CONTENIDO'
        razon = 'Título parecido y fecha cercana, pero el contenido no respalda identidad editorial.'
    else:
        estado = 'TITULO_REPETIDO_NO_CONFIRMADO'
        razon = 'La coincidencia nominal carece de evidencia independiente suficiente.'

    return {
        'estado': estado,
        'razon': razon,
        'similitud_titulo': similitud_titulo,
        'similitud_contenido': similitud_cuerpo,
        'dias_entre_fechas_editoriales': dias,
        'misma_url_canonicalizada': url_igual,
    }


def detectar_candidatos(registros):
    """Devuelve pares explicables para revisión; no persiste ni oculta nada.

    Cada registro admite: pk/id, fuente, titulo, url, fecha_publicacion,
    contenido_completo y contenido. La fecha_captura se ignora deliberadamente.
    """
    filas = _preparar(registros)
    resultados = []
    for i, j in _pares_candidatos(filas):
        evaluacion = _evaluar(filas[i], filas[j])
        resultados.append({
            'estado': evaluacion.pop('estado'),
            'razon': evaluacion.pop('razon'),
            'publicaciones': [
                {k: fila.get(k) for k in ('pk', 'fuente_original', 'titulo', 'url', 'fecha_publicacion', 'contenido_completo')}
                for fila in (filas[i], filas[j])
            ],
            **evaluacion,
        })
    return resultados
