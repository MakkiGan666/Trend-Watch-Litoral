"""Entradilla y párrafos para la vista de noticia, sin llamadas externas."""

import re
from html import unescape

from django.utils.html import strip_tags


def preparar_lectura(contenido):
    texto = unescape(strip_tags(contenido or '')).replace('\r\n', '\n').strip()
    parrafos = [parrafo.strip() for parrafo in re.split(r'\n\s*\n', texto) if parrafo.strip()]
    if not parrafos:
        return {'resumen': '', 'primer_parrafo': '', 'resto': ''}

    primero = parrafos[0]
    frases = re.split(r'(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡0-9])', ' '.join(primero.split()))
    resumen = ''
    for frase in frases:
        candidato = f'{resumen} {frase}'.strip()
        if len(candidato) > 240:
            break
        resumen = candidato
        if len(resumen) >= 100:
            break
    if not resumen:
        resumen = ' '.join(primero.split())[:241].rsplit(' ', 1)[0].rstrip(' ,;:') + '…'

    return {
        'resumen': resumen,
        'primer_parrafo': primero,
        'resto': '\n\n'.join(parrafos[1:]),
    }
