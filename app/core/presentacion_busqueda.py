"""Datos de presentación; nunca devuelve HTML marcado como seguro."""
import unicodedata
from urllib.parse import unquote, urlsplit

from .services.buscador import plegar


def segmentos_resaltados(texto, terminos):
    texto = unicodedata.normalize('NFC', texto)
    comparable = plegar(texto)
    indices = [i for i, c in enumerate(texto) for _ in c.lower()]
    intervalos = []
    for termino in terminos:
        if not termino:
            continue
        inicio = comparable.find(termino)
        while inicio != -1:
            intervalos.append((indices[inicio], indices[inicio + len(termino) - 1] + 1))
            inicio = comparable.find(termino, inicio + 1)
    unidos = []
    for inicio, fin in sorted(intervalos):
        if unidos and inicio <= unidos[-1][1]:
            unidos[-1] = (unidos[-1][0], max(fin, unidos[-1][1]))
        else:
            unidos.append((inicio, fin))
    segmentos, posicion = [], 0
    for inicio, fin in unidos:
        if inicio > posicion:
            segmentos.append({'texto': texto[posicion:inicio], 'coincide': False})
        segmentos.append({'texto': texto[inicio:fin], 'coincide': True})
        posicion = fin
    if posicion < len(texto):
        segmentos.append({'texto': texto[posicion:], 'coincide': False})
    return segmentos


def imagen_segura(valor):
    if not isinstance(valor, str):
        return None
    url = valor.strip()
    if not url or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        return None
    decodificada = unquote(url)
    if '\\' in decodificada or any(ord(c) < 32 or ord(c) == 127 for c in decodificada):
        return None
    try:
        partes = urlsplit(url)
        if partes.scheme.lower() in ('http', 'https') and partes.hostname and not partes.username and not partes.password:
            return url
        if not partes.scheme and not partes.netloc and url.startswith('/') and not decodificada.startswith('//'):
            return url
    except ValueError:
        pass
    return None
