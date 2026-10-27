"""Búsqueda pública de lectura; las comparaciones se ejecutan en la base."""
import unicodedata
from html import unescape

from django.core.paginator import EmptyPage, Paginator
from django.db.models import Q
from django.db.models.functions import Coalesce
from django.utils.html import strip_tags

from core.models import Publicacion
from core.busqueda_texto_v1 import (
    BASES_V1 as BASES, VOCALES_V1 as VOCALES,
    TextoComparableV1 as TextoComparable, plegar_v1 as plegar,
)

TAMANO = 20


class EntradaInvalida(ValueError):
    def __init__(self, codigo, mensaje):
        self.codigo = codigo
        super().__init__(mensaje)


def validar_consulta(valor):
    if valor is None:
        raise EntradaInvalida('consulta_invalida', 'El parámetro q es obligatorio.')
    if any(unicodedata.category(c).startswith('C') and c not in '\t\n\r' for c in valor):
        raise EntradaInvalida('consulta_invalida', 'La consulta contiene controles no permitidos.')
    consulta = ' '.join(unicodedata.normalize('NFC', valor).split())
    palabras = consulta.split()
    if not 2 <= len(consulta) <= 150 or len(palabras) > 10:
        raise EntradaInvalida('consulta_invalida', 'q debe tener entre 2 y 150 caracteres y hasta 10 términos.')
    return consulta, list(dict.fromkeys(plegar(p) for p in palabras))


def buscar(consulta, pagina='1'):
    consulta, terminos = validar_consulta(consulta)
    if not pagina or any(c not in '0123456789' for c in pagina) or len(pagina) > 10 or int(pagina) < 1:
        raise EntradaInvalida('pagina_invalida', 'page debe ser un entero positivo dentro del rango.')
    noticias = publicaciones_coincidentes(terminos)
    paginador = Paginator(noticias, TAMANO)
    try:
        resultado = paginador.page(int(pagina))
    except EmptyPage:
        raise EntradaInvalida('pagina_invalida', 'La página está fuera del rango.') from None
    return consulta, terminos, resultado


def publicaciones_coincidentes(terminos):
    """QuerySet sin evaluar, compartido con el diagnóstico SQL."""
    noticias = Publicacion.objects.all()
    for termino in terminos:
        noticias = noticias.filter(Q(titulo_busqueda__contains=termino) | Q(contenido_busqueda__contains=termino))
    return noticias.order_by(Coalesce('fecha_publicacion', 'fecha_captura').desc(nulls_last=True), '-pk')


def extracto(contenido, terminos):
    texto = ' '.join(unescape(strip_tags(contenido)).split())
    # NFC unifica las vocales descompuestas antes de buscar contexto.
    texto = unicodedata.normalize('NFC', texto)
    comparable = plegar(texto)
    posiciones = [comparable.find(t) for t in terminos if t in comparable]
    coincidencia = min(posiciones) if posiciones else None
    if coincidencia is not None and len(comparable) != len(texto):
        # lower puede expandir caracteres (İ -> i + punto). Recorrer el
        # plegado por carácter mapea el índice al original NFC sin alterarlo.
        consumidos = 0
        for indice, caracter in enumerate(texto):
            consumidos += len(caracter.lower())
            if consumidos > coincidencia:
                coincidencia = indice
                break
    inicio = max(0, coincidencia - 80) if coincidencia is not None else 0
    final = inicio + 240
    return ('…' if inicio else '') + texto[inicio:final] + ('…' if final < len(texto) else '')
