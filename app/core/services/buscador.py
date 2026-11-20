"""Búsqueda pública de lectura; las comparaciones se ejecutan en la base."""
import unicodedata
from html import unescape
from datetime import date

from django.core.paginator import EmptyPage, Paginator
from django.db.models import (
    DateTimeField, Exists, F, FilteredRelation, IntegerField, OuterRef, Q,
    Subquery, Value, When, Case, Window,
)
from django.db.models.functions import Coalesce
from django.db.models.functions.window import RowNumber
from django.utils.html import strip_tags

from core.models import GrupoEditorial, MiembroGrupoEditorial, Publicacion, PublicacionTema
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
    grupos_activos = grupos_editoriales_activos()
    noticias = publicaciones_coincidentes(terminos, filtros, grupos_activos=grupos_activos)
    paginador = Paginator(noticias, TAMANO)
    try:
        resultado = paginador.page(int(pagina))
    except EmptyPage:
        raise EntradaInvalida('pagina_invalida', 'La página está fuera del rango.') from None
    resultado.filtros = filtros
    _adjuntar_versiones_editoriales(resultado, grupos_activos=grupos_activos)
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


def grupos_editoriales_activos():
    """Consulta el estado actual; no conserva decisiones entre solicitudes."""
    return MiembroGrupoEditorial.objects.filter(
        vigente=True,
        decision=MiembroGrupoEditorial.Decision.APROBADO,
        grupo__estado=GrupoEditorial.Estado.ACTIVO,
    ).exists()


def _coincidencias(terminos, filtros=None, *, grupos_activos=None):
    """Coincidencias; usa identidad directa cuando no hay grupos aprobados."""
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
        noticias = noticias.filter(Exists(PublicacionTema.objects.filter(
            id_publicacion_api_id=OuterRef('pk'),
            id_temas__id_categoria__nombre_categoria__iexact=filtros['categoria'],
        )))
    if grupos_activos is None:
        grupos_activos = grupos_editoriales_activos()
    if not grupos_activos:
        return noticias.annotate(_representante_editorial=F('pk'))
    return noticias.annotate(
        _membresia_editorial_activa=FilteredRelation(
            'membresias_editoriales',
            condition=Q(
                membresias_editoriales__vigente=True,
                membresias_editoriales__decision=MiembroGrupoEditorial.Decision.APROBADO,
            ),
        ),
    ).annotate(
        _representante_editorial=Case(
            When(
                _membresia_editorial_activa__grupo__estado=GrupoEditorial.Estado.ACTIVO,
                then=F('_membresia_editorial_activa__grupo__representante_id'),
            ),
            default=F('pk'), output_field=IntegerField(),
        ),
    )


def publicaciones_coincidentes(terminos, filtros=None, *, grupos_activos=None):
    """Una fila elegible por grupo, seleccionada y ordenada en SQL.

    Con cero grupos vigentes conserva la consulta plana previa. Con grupos,
    una ventana elige primero la coincidencia más reciente de cada identidad;
    no se reinyecta el QuerySet completo en subconsultas de agrupación.
    """
    if grupos_activos is None:
        grupos_activos = grupos_editoriales_activos()
    coincidencias = _coincidencias(terminos, filtros, grupos_activos=grupos_activos)
    fecha_coincidencia = Coalesce('fecha_publicacion', 'fecha_captura', output_field=DateTimeField())
    if not grupos_activos:
        return coincidencias.annotate(
            _fecha_relevancia=fecha_coincidencia,
            _fecha_representante=fecha_coincidencia,
            _coincidencia_id=F('pk'),
            _grupo_editorial_id=Value(None, output_field=IntegerField()),
        ).order_by(
            F('_fecha_relevancia').desc(nulls_last=True), '-pk',
        )

    return coincidencias.annotate(
        _fecha_relevancia=fecha_coincidencia,
        _rango_editorial=Window(
            expression=RowNumber(),
            partition_by=[F('_representante_editorial')],
            order_by=[F('_fecha_relevancia').desc(nulls_last=True), F('pk').desc()],
        ),
        _fecha_representante=Case(
            When(
                _membresia_editorial_activa__grupo__estado=GrupoEditorial.Estado.ACTIVO,
                then=Coalesce(
                    F('_membresia_editorial_activa__grupo__representante__fecha_publicacion'),
                    F('_membresia_editorial_activa__grupo__representante__fecha_captura'),
                    output_field=DateTimeField(),
                ),
            ),
            default=Coalesce('fecha_publicacion', 'fecha_captura', output_field=DateTimeField()),
            output_field=DateTimeField(),
        ),
        _grupo_editorial_id=Case(
            When(
                _membresia_editorial_activa__grupo__estado=GrupoEditorial.Estado.ACTIVO,
                then=F('_membresia_editorial_activa__grupo_id'),
            ),
            default=Value(None, output_field=IntegerField()), output_field=IntegerField(),
        ),
        _coincidencia_id=F('pk'),
    ).filter(_rango_editorial=1).order_by(
        F('_fecha_relevancia').desc(nulls_last=True),
        F('_fecha_representante').desc(nulls_last=True),
        F('_representante_editorial').desc(),
    )


def _adjuntar_versiones_editoriales(pagina, *, grupos_activos=False):
    publicaciones = list(pagina.object_list)
    pagina.object_list = publicaciones
    if not publicaciones:
        return
    categorias_por_publicacion = {}
    for publicacion in publicaciones:
        publicacion._presentacion = publicacion
        publicacion._coincidencia = publicacion
        publicacion._categorias_presentacion = sorted(
            categorias_por_publicacion.get(publicacion.pk, set()), key=str.casefold,
        )
        publicacion._versiones_originales = []
        publicacion._representante = publicacion
        publicacion._grupo_editorial_id = None
    if not grupos_activos:
        return
    ids = [publicacion.pk for publicacion in publicaciones]
    grupos_candidatos = MiembroGrupoEditorial.objects.filter(
        publicacion_id__in=ids, vigente=True,
        decision=MiembroGrupoEditorial.Decision.APROBADO,
        grupo__estado=GrupoEditorial.Estado.ACTIVO,
    ).values('grupo_id')
    membresias = MiembroGrupoEditorial.objects.filter(
        grupo_id__in=Subquery(grupos_candidatos),
        vigente=True,
        decision=MiembroGrupoEditorial.Decision.APROBADO,
        grupo__estado=GrupoEditorial.Estado.ACTIVO,
    ).select_related('grupo__representante', 'publicacion').only(
        'grupo_id', 'grupo__representante_id', 'grupo__representante__titulo',
        'grupo__representante__fuente', 'grupo__representante__fecha_publicacion',
        'publicacion_id', 'publicacion__id_publicacion_api', 'publicacion__titulo',
        'publicacion__fuente', 'publicacion__fecha_publicacion',
    ).order_by('grupo__representante_id', 'publicacion_id')
    por_representante = {}
    por_publicacion = {}
    for membresia in membresias:
        representante_id = membresia.grupo.representante_id
        por_representante.setdefault(representante_id, []).append(membresia.publicacion)
        por_publicacion[membresia.publicacion_id] = membresia
    for publicacion in publicaciones:
        membresia = por_publicacion.get(publicacion.pk)
        if membresia:
            publicacion._grupo_editorial_id = membresia.grupo_id
            publicacion._representante = membresia.grupo.representante
            publicacion._versiones_originales = por_representante.get(membresia.grupo.representante_id, [])
    ids_categorias = [publicacion.pk for publicacion in publicaciones if publicacion._grupo_editorial_id]
    categorias_por_publicacion = {}
    if ids_categorias:
        for publicacion_id, categoria in PublicacionTema.objects.filter(
            id_publicacion_api_id__in=ids_categorias,
        ).values_list('id_publicacion_api_id', 'id_temas__id_categoria__nombre_categoria').distinct():
            categorias_por_publicacion.setdefault(publicacion_id, set()).add(categoria)
        for publicacion in publicaciones:
            publicacion._categorias_presentacion = sorted(
                categorias_por_publicacion.get(publicacion.pk, set()), key=str.casefold,
            )


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
