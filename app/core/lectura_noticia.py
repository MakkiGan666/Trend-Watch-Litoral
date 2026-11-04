"""Entradilla y párrafos para la vista de noticia, sin llamadas externas.

El resultado es texto, no HTML seguro: la plantilla debe mantener autoescape.
"""

import re
from html.parser import HTMLParser

LIMITE_RESUMEN = 240
BLOQUES = {
    'address', 'article', 'aside', 'blockquote', 'dd', 'div', 'dl', 'dt',
    'fieldset', 'figcaption', 'figure', 'footer', 'form', 'h1', 'h2', 'h3',
    'h4', 'h5', 'h6', 'header', 'hr', 'li', 'main', 'nav', 'ol', 'p',
    'pre', 'section', 'table', 'tbody', 'td', 'th', 'thead', 'tr', 'ul',
}


class _TextoNoticia(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.partes = []
        self.omitir = None

    def handle_starttag(self, tag, attrs):
        if self.omitir:
            return
        if tag in {'script', 'style'}:
            self.omitir = tag
            self.partes.append(' ')
        elif tag == 'br':
            self.partes.append('\n')
        elif tag in BLOQUES:
            self.partes.append('\n\n')

    def handle_endtag(self, tag):
        if self.omitir:
            if tag == self.omitir:
                self.omitir = None
                self.partes.append(' ')
        elif tag in BLOQUES:
            self.partes.append('\n\n')

    def handle_data(self, data):
        if not self.omitir:
            self.partes.append(data)


def _resumir(primero):
    texto = ' '.join(primero.split())
    frases = re.split(r'(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡0-9])', texto)
    resumen = ''
    for frase in frases:
        candidato = f'{resumen} {frase}'.strip()
        if len(candidato) > LIMITE_RESUMEN:
            break
        resumen = candidato
        if len(resumen) >= 100:
            break
    if resumen:
        return resumen
    # Reservar un carácter para la elipsis, incluso sin espacios en la entrada.
    corte = texto[:LIMITE_RESUMEN - 1]
    if not texto[LIMITE_RESUMEN - 1].isspace() and ' ' in corte:
        corte = corte.rsplit(' ', 1)[0]
    return corte.rstrip(' ,;:') + '…'


def preparar_lectura(contenido):
    if contenido is None:
        contenido = ''
    if not isinstance(contenido, str):
        raise TypeError('El contenido debe ser texto o None.')
    parser = _TextoNoticia()
    try:
        parser.feed(contenido)
        parser.close()
        texto = ''.join(parser.partes)
    except (AssertionError, ValueError):
        # Declaraciones inválidas pueden ser rechazadas por HTMLParser.
        # Conservar la fuente como texto literal; nunca marcarla como segura.
        texto = contenido
    texto = (texto.replace('\r\n', '\n').replace('\r', '\n')
             .replace('\u2028', '\n').replace('\u2029', '\n\n').strip())
    parrafos = [parrafo.strip() for parrafo in re.split(r'\n\s*\n', texto) if parrafo.strip()]
    if not parrafos:
        return {'resumen': '', 'primer_parrafo': '', 'resto': ''}
    primero = parrafos[0]
    return {
        'resumen': _resumir(primero),
        'primer_parrafo': primero,
        'resto': '\n\n'.join(parrafos[1:]),
    }
