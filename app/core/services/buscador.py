"""Búsqueda pública de lectura; las comparaciones se ejecutan en la base."""
import unicodedata
from html import unescape
from datetime import date

from django.core.paginator import EmptyPage, Paginator
from django.db.models import DateTimeField, F, IntegerField, Max, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.utils.html import strip_tags

from core.models import GrupoEditorial, MiembroGrupoEditorial, Publicacion
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


def buscar(consulta, pagina='1', filtros=None):
    consulta, terminos = validar_consulta(consulta)
    if not pagina or any(c not in '0123456789' for c in pagina) or len(pagina) > 10 or int(pagina) < 1:
        raise EntradaInvalida('pagina_invalida', 'page debe ser un entero positivo dentro del rango.')
    filtros = validar_filtros(filtros or {})
    noticias = publicaciones_coincidentes(terminos, filtros)
    paginador = Paginator(noticias, TAMANO)
    try:
        resultado = paginador.page(int(pagina))
    except EmptyPage:
        raise EntradaInvalida('pagina_invalida', 'La página está fuera del rango.') from None
    resultado.filtros = filtros
    _adjuntar_versiones_editoriales(resultado)
    return consulta, terminos, resultado


def validar_filtros(filtros):
    """Normaliza filtros GET compartidos por HTML, API y autocompletado."""
    filtros = filtros or {}
    normalizados = {}
    for clave in ('desde', 'hasta'):
        valor = str(filtros.get(clave, '') or '').strip()
        if not valor:
            normalizados[clave] = None
            continue
        try:
            fecha = date.fromisoformat(valor)
        except (TypeError, ValueError):
            raise EntradaInvalida('filtro_invalido', f'{clave} debe usar el formato AAAA-MM-DD.') from None
        if fecha.isoformat() != valor:
            raise EntradaInvalida('filtro_invalido', f'{clave} debe usar el formato AAAA-MM-DD.')
        normalizados[clave] = fecha
    if normalizados['desde'] and normalizados['hasta'] and normalizados['desde'] > normalizados['hasta']:
        raise EntradaInvalida('filtro_invalido', 'desde no puede ser posterior a hasta.')
    for clave, maximo in (('fuente', 100), ('categoria', 100)):
        valor = str(filtros.get(clave, '') or '').strip()
        if len(valor) > maximo or any(unicodedata.category(c).startswith('C') for c in valor):
            raise EntradaInvalida('filtro_invalido', f'{clave} no es válido.')
        normalizados[clave] = valor
    return normalizados


def _coincidencias(terminos, filtros=None):
    """Publicaciones que coinciden, anotadas con representante editorial vigente."""
    noticias = Publicacion.objects.all()
    for termino in terminos:
        noticias = noticias.filter(
            Q(titulo_busqueda__contains=termino)
            | Q(contenido_busqueda__contains=termino)
            | Q(fuente__icontains=termino)
        )
    filtros = validar_filtros(filtros or {})
    fecha_efectiva = Coalesce('fecha_publicacion', 'fecha_captura', output_field=DateTimeField())
    if filtros['desde']:
        noticias = noticias.annotate(_fecha_efectiva=fecha_efectiva).filter(_fecha_efectiva__date__gte=filtros['desde'])
    if filtros['hasta']:
        noticias = noticias.annotate(_fecha_efectiva=fecha_efectiva).filter(_fecha_efectiva__date__lte=filtros['hasta'])
    if filtros['fuente']:
        noticias = noticias.filter(fuente__iexact=filtros['fuente'])
    if filtros['categoria']:
        noticias = noticias.filter(temas__id_categoria__nombre_categoria__iexact=filtros['categoria'])
    # La relación temática puede producir varias filas para una publicación.
    noticias = noticias.distinct()
    representante_activo = MiembroGrupoEditorial.objects.filter(
        publicacion_id=OuterRef('pk'), vigente=True,
        decision=MiembroGrupoEditorial.Decision.APROBADO,
        grupo__estado=GrupoEditorial.Estado.ACTIVO,
    ).order_by().values('grupo__representante_id')[:1]
    return noticias.annotate(
        _representante_editorial=Coalesce(
            Subquery(representante_activo, output_field=IntegerField()), F('pk'),
            output_field=IntegerField(),
        ),
    )


def publicaciones_coincidentes(terminos, filtros=None):
    """Representantes únicos; agrupa antes de contar, ordenar y paginar.

    La fecha más reciente entre las publicaciones coincidentes conserva la
    posición editorial del grupo aunque el texto coincida en un miembro.
    """
    coincidencias = _coincidencias(terminos, filtros)
    fecha_coincidencia = Coalesce('fecha_publicacion', 'fecha_captura', output_field=DateTimeField())
    grupos = coincidencias.order_by().values('_representante_editorial').annotate(
        _fecha_relevancia=Max(fecha_coincidencia),
    )
    mejor_coincidencia = coincidencias.filter(
        _representante_editorial=OuterRef('pk'),
    ).order_by(fecha_coincidencia.desc(nulls_last=True), '-pk').values('pk')[:1]
    fecha_relevancia = grupos.filter(
        _representante_editorial=OuterRef('pk'),
    ).values('_fecha_relevancia')[:1]
    grupo_representante = MiembroGrupoEditorial.objects.filter(
        publicacion_id=OuterRef('pk'),
        rol=MiembroGrupoEditorial.Rol.REPRESENTANTE,
        decision=MiembroGrupoEditorial.Decision.APROBADO,
        vigente=True,
        grupo__estado=GrupoEditorial.Estado.ACTIVO,
    ).order_by().values('grupo_id')[:1]
    fecha_representante = Coalesce('fecha_publicacion', 'fecha_captura', output_field=DateTimeField())
    return Publicacion.objects.filter(
        pk__in=Subquery(grupos.values('_representante_editorial')),
    ).annotate(
        _fecha_relevancia=Subquery(fecha_relevancia, output_field=DateTimeField()),
        _fecha_representante=fecha_representante,
        _coincidencia_id=Subquery(mejor_coincidencia, output_field=IntegerField()),
        _grupo_editorial_id=Subquery(grupo_representante, output_field=IntegerField()),
    ).order_by(
        F('_fecha_relevancia').desc(nulls_last=True),
        F('_fecha_representante').desc(nulls_last=True), '-pk',
    )


def _adjuntar_versiones_editoriales(pagina):
    publicaciones = list(pagina.object_list)
    pagina.object_list = publicaciones
    if not publicaciones:
        return
    ids_coincidencia = {
        publicacion._coincidencia_id for publicacion in publicaciones
        if publicacion._coincidencia_id != publicacion.pk
    }
    coincidencias = {
        publicacion.pk: publicacion
        for publicacion in Publicacion.objects.filter(pk__in=ids_coincidencia)
    }
    for publicacion in publicaciones:
        publicacion._coincidencia = coincidencias.get(publicacion._coincidencia_id, publicacion)
        publicacion._versiones_originales = []
    agrupadas = [publicacion for publicacion in publicaciones if publicacion._grupo_editorial_id]
    if not agrupadas:
        return
    membresias = MiembroGrupoEditorial.objects.filter(
        grupo_id__in=[publicacion._grupo_editorial_id for publicacion in agrupadas],
        grupo__estado=GrupoEditorial.Estado.ACTIVO,
        decision=MiembroGrupoEditorial.Decision.APROBADO,
        vigente=True,
    ).select_related('grupo', 'publicacion').only(
        'grupo_id', 'grupo__representante_id', 'publicacion_id',
        'publicacion__id_publicacion_api', 'publicacion__titulo',
        'publicacion__fuente', 'publicacion__fecha_publicacion',
    ).order_by('grupo__representante_id', 'publicacion_id')
    por_representante = {}
    for membresia in membresias:
        representante_id = membresia.grupo.representante_id
        por_representante.setdefault(representante_id, []).append(membresia.publicacion)
    for publicacion in publicaciones:
        if publicacion._grupo_editorial_id:
            publicacion._versiones_originales = por_representante.get(publicacion.pk, [])


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
