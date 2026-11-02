"""Filtro básico de lenguaje ofensivo para comentarios públicos.

Las expresiones se comparan como palabras o frases completas tras normalizar
tildes y algunas sustituciones frecuentes. No sustituye la moderación humana.
"""
import re
import unicodedata


EXPRESIONES_BLOQUEADAS = (
    'hijo de puta', 'hija de puta', 'puta', 'puto', 'mierda',
    'pelotudo', 'pelotuda', 'boludo', 'boluda', 'forro', 'forra',
    'concha de tu madre', 'la concha', 'verga', 'pija',
    'hay que matar a', 'maten a todos', 'maten a los', 'exterminar a',
)


def _normalizar(texto):
    texto = unicodedata.normalize('NFKD', texto.casefold())
    texto = ''.join(letra for letra in texto if not unicodedata.combining(letra))
    texto = texto.translate(str.maketrans({'@': 'a', '0': 'o', '1': 'i', '3': 'e', '$': 's'}))
    return ' '.join(re.findall(r'[a-z0-9]+', texto))


def contiene_lenguaje_inapropiado(texto):
    normalizado = f' {_normalizar(texto)} '
    return any(f' {_normalizar(expresion)} ' in normalizado for expresion in EXPRESIONES_BLOQUEADAS)
