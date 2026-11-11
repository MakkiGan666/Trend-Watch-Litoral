"""Lectura de la agenda mediática registrada: territorio, temas y tiempo.

Sólo consulta datos existentes: no ejecuta ingesta ni IA, no modifica
registros y no completa períodos, territorios ni resultados sin observaciones.
Lo usan la portada pública y el panel de análisis para que ambos cuenten igual.
"""
from collections import defaultdict
from datetime import timedelta

from django.db.models import Count, Max, Q
from django.db.models.functions import Coalesce, TruncDate, TruncMonth
from django.utils import timezone
from django.utils.text import slugify

from core.busqueda_texto_v1 import plegar_v1
from core.fechas import ZONA_LOCAL
from core.localidades import DEPARTAMENTOS, departamento_de_ubicacion
from core.models import Comentario, Locacion, Publicacion
from core.services.clasificacion import CATEGORIAS_PROYECTO
from core.services.indicadores import ANALISIS_VALIDO, publicaciones_con_estado
from core.services.sentimiento_comentarios import sentimiento_vigente

SIN_IDENTIFICAR = 'sin-identificar'
SIN_CATEGORIA = 'Sin categoría asociada'
NOMBRES_DEPARTAMENTO = {d['slug']: d['nombre'] for d in DEPARTAMENTOS}


def barras(filas):
    maximo = max((f['total'] for f in filas), default=1) or 1
    return [{**f, 'ancho': round(f['total'] * 100 / maximo, 2)} for f in filas]


def variacion(actual, anterior):
    """Porcentaje de cambio; None si no hay base de comparación."""
    if not anterior:
        return None
    return round((actual - anterior) * 100 / anterior)


def hoy_local():
    return timezone.now().astimezone(ZONA_LOCAL).date()


def con_fecha_base(queryset):
    """Fecha del medio cuando existe; si no, la de captura. Día en hora argentina."""
    return queryset.annotate(fecha_base=Coalesce('fecha_publicacion', 'fecha_captura')).annotate(
        dia_base=TruncDate('fecha_base', tzinfo=ZONA_LOCAL),
    )


def unicas(queryset):
    """Una fila por publicación aunque los filtros crucen temas o ubicaciones."""
    return Publicacion.objects.filter(pk__in=queryset.order_by().values('pk'))


# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------


def ubicaciones_por_departamento():
    """Nombres de Locacion reconocidos para cada uno de los 17 departamentos."""
    ubicaciones = {d['slug']: [] for d in DEPARTAMENTOS}
    for nombre in Locacion.objects.order_by().values_list('location', flat=True).distinct():
        slug = departamento_de_ubicacion(nombre)
        if slug:
            ubicaciones[slug].append(nombre)
    return ubicaciones


def filtrar_departamento(queryset, slug, ubicaciones):
    if slug == SIN_IDENTIFICAR:
        reconocidas = [nombre for grupo in ubicaciones.values() for nombre in grupo]
        return queryset.exclude(departamento__in=list(ubicaciones)).exclude(locacion__location__in=reconocidas)
    return queryset.filter(Q(departamento=slug) | Q(locacion__location__in=ubicaciones[slug]))


def filtrar_texto(queryset, consulta):
    """Cada término debe aparecer en título, contenido o fuente (sin tildes ni mayúsculas)."""
    for termino in (consulta or '').split():
        comparable = plegar_v1(termino)
        queryset = queryset.filter(
            Q(titulo_busqueda__contains=comparable)
            | Q(contenido_busqueda__contains=comparable)
            | Q(fuente__icontains=termino)
        )
    return queryset


# ---------------------------------------------------------------------------
# Territorio
# ---------------------------------------------------------------------------


def publicaciones_por_departamento(base):
    """slug -> publicaciones, por departamento de ingesta o ubicación reconocida."""
    por_departamento = defaultdict(set)
    for pk, slug in base.order_by().values_list('pk', 'departamento'):
        if slug in NOMBRES_DEPARTAMENTO:
            por_departamento[slug].add(pk)
    ubicaciones = Locacion.objects.filter(id_publicacion_api__in=base.order_by().values('pk'))
    for pk, nombre in ubicaciones.values_list('id_publicacion_api', 'location'):
        slug = departamento_de_ubicacion(nombre)
        if slug:
            por_departamento[slug].add(pk)
    return por_departamento


def cobertura_territorial(base):
    """Los 17 departamentos ordenados por cobertura, sin omitir los que no tienen."""
    por_departamento = publicaciones_por_departamento(base)
    total = base.count()
    asociadas = set().union(*por_departamento.values()) if por_departamento else set()
    filas = barras(sorted(
        ({'slug': d['slug'], 'nombre': d['nombre'], 'total': len(por_departamento[d['slug']])}
         for d in DEPARTAMENTOS),
        key=lambda fila: (-fila['total'], fila['nombre']),
    ))
    con_cobertura = [fila for fila in filas if fila['total']]
    return {
        'departamentos': filas,
        'con_cobertura': len(con_cobertura),
        'cantidad': len(DEPARTAMENTOS),
        'sin_cobertura': [fila for fila in filas if not fila['total']],
        'mayor': con_cobertura[0] if con_cobertura else None,
        'menor': con_cobertura[-1] if len(con_cobertura) > 1 else None,
        'sin_identificar': total - len(asociadas),
        'total': total,
    }


# ---------------------------------------------------------------------------
# Temas
# ---------------------------------------------------------------------------


def conteo_categorias(base):
    """Publicaciones por categoría; las sin asociación se informan al final."""
    filas = (base.order_by()
             .values('temas__id_categoria', 'temas__id_categoria__nombre_categoria')
             .annotate(total=Count('pk', distinct=True)))
    resultado = []
    for fila in filas:
        nombre = fila['temas__id_categoria__nombre_categoria']
        resultado.append({
            'id': fila['temas__id_categoria'],
            'nombre': nombre or SIN_CATEGORIA,
            'slug': slugify(nombre) if nombre in CATEGORIAS_PROYECTO else '',
            'total': fila['total'],
        })
    return sorted(resultado, key=lambda f: (f['id'] is None, -f['total'], f['nombre']))


# ---------------------------------------------------------------------------
# Tiempo
# ---------------------------------------------------------------------------


def ultimo_dia_con_datos(queryset):
    """Último día con publicaciones hasta hoy; las fechas futuras no anclan períodos."""
    return con_fecha_base(queryset).filter(dia_base__lte=hoy_local()).aggregate(
        ultimo=Max('dia_base'),
    )['ultimo']


def comparar_periodos(queryset, inicio, fin):
    """Compara [inicio, fin] con el período inmediatamente anterior de igual duración."""
    dias = (fin - inicio).days + 1
    fin_anterior = inicio - timedelta(days=1)
    inicio_anterior = fin_anterior - timedelta(days=dias - 1)
    fechadas = con_fecha_base(queryset)
    actual = unicas(fechadas.filter(dia_base__gte=inicio, dia_base__lte=fin))
    anterior = unicas(fechadas.filter(dia_base__gte=inicio_anterior, dia_base__lte=fin_anterior))
    total_actual, total_anterior = actual.count(), anterior.count()
    temas_actual = {f['nombre']: f for f in conteo_categorias(actual) if f['id'] is not None}
    temas_anterior = {f['nombre']: f for f in conteo_categorias(anterior) if f['id'] is not None}
    temas = []
    for nombre in set(temas_actual) | set(temas_anterior):
        referencia = temas_actual.get(nombre) or temas_anterior[nombre]
        a = temas_actual.get(nombre, {}).get('total', 0)
        b = temas_anterior.get(nombre, {}).get('total', 0)
        temas.append({
            'id': referencia['id'], 'nombre': nombre, 'slug': referencia['slug'],
            'actual': a, 'anterior': b, 'diferencia': a - b, 'variacion': variacion(a, b),
        })
    temas.sort(key=lambda t: (-t['actual'], -t['anterior'], t['nombre']))
    maximo = max((t['actual'] for t in temas), default=0) or 1
    for tema in temas:
        tema['ancho'] = round(tema['actual'] * 100 / maximo, 2)
    return {
        'inicio': inicio, 'fin': fin, 'dias': dias,
        'inicio_anterior': inicio_anterior, 'fin_anterior': fin_anterior,
        'actual': total_actual, 'anterior': total_anterior,
        'diferencia': total_actual - total_anterior,
        'variacion': variacion(total_actual, total_anterior),
        'temas': temas,
        'en_aumento': sorted((t for t in temas if t['diferencia'] > 0),
                             key=lambda t: (-t['diferencia'], t['nombre']))[:5],
        'en_descenso': sorted((t for t in temas if t['diferencia'] < 0),
                              key=lambda t: (t['diferencia'], t['nombre']))[:5],
    }


def serie_semanal(queryset, fin, semanas=12):
    """Publicaciones por semana (de 7 días) que terminan en `fin`."""
    inicio = fin - timedelta(days=semanas * 7 - 1)
    totales = [0] * semanas
    por_dia = (con_fecha_base(queryset).filter(dia_base__gte=inicio, dia_base__lte=fin)
               .order_by().values('dia_base').annotate(total=Count('pk', distinct=True)))
    for fila in por_dia:
        totales[(fila['dia_base'] - inicio).days // 7] += fila['total']
    maximo = max(totales) or 1
    return [{
        'inicio': inicio + timedelta(days=7 * i),
        'fin': inicio + timedelta(days=7 * i + 6),
        'total': total,
        'alto': round(total * 100 / maximo, 2),
    } for i, total in enumerate(totales)]


def evolucion_mensual_temas(base, limite_temas=6, limite_meses=6):
    """Matriz tema × mes con los meses que tienen publicaciones (sin rellenar huecos)."""
    fechadas = con_fecha_base(base).annotate(mes=TruncMonth('fecha_base', tzinfo=ZONA_LOCAL))
    claves = sorted({(m.year, m.month) for m in fechadas.order_by().values_list('mes', flat=True).distinct() if m})
    claves = claves[-limite_meses:]
    if not claves:
        return None
    filas = (fechadas.order_by()
             .values('mes', 'temas__id_categoria', 'temas__id_categoria__nombre_categoria')
             .annotate(total=Count('pk', distinct=True)))
    conteo = defaultdict(lambda: defaultdict(int))
    nombres = {}
    for fila in filas:
        if fila['temas__id_categoria'] is None or fila['mes'] is None:
            continue
        clave = (fila['mes'].year, fila['mes'].month)
        if clave in claves:
            conteo[fila['temas__id_categoria']][clave] += fila['total']
            nombres[fila['temas__id_categoria']] = fila['temas__id_categoria__nombre_categoria']
    principales = sorted(conteo, key=lambda cid: (-sum(conteo[cid].values()), nombres[cid]))[:limite_temas]
    if not principales:
        return None
    maximo = max(conteo[cid][clave] for cid in principales for clave in claves) or 1
    return {
        'meses': [f'{mes:02d}/{anio}' for anio, mes in claves],
        'temas': [{
            'id': cid, 'nombre': nombres[cid],
            'slug': slugify(nombres[cid]) if nombres[cid] in CATEGORIAS_PROYECTO else '',
            'total': sum(conteo[cid][clave] for clave in claves),
            'celdas': [{'mes': f'{mes:02d}/{anio}', 'total': conteo[cid][(anio, mes)],
                        'nivel': round(conteo[cid][(anio, mes)] / maximo, 2)} for anio, mes in claves],
        } for cid in principales],
    }


# ---------------------------------------------------------------------------
# Análisis de contenido
# ---------------------------------------------------------------------------


def sentimiento_publicaciones(base):
    """Sentimiento automático del texto de las noticias (un único análisis válido)."""
    datos = publicaciones_con_estado(base).filter(ANALISIS_VALIDO)
    return barras([
        {'nombre': 'Positivo', 'total': datos.filter(polaridad_registrada__gt=0).count()},
        {'nombre': 'Neutral', 'total': datos.filter(polaridad_registrada=0).count()},
        {'nombre': 'Negativo', 'total': datos.filter(polaridad_registrada__lt=0).count()},
    ])


def sentimiento_comentarios(base):
    """Sentimiento automático de los comentarios publicados, sólo si sigue vigente."""
    conteo = {'positivo': 0, 'neutral': 0, 'negativo': 0}
    sin_analisis = 0
    comentarios = (Comentario.objects
                   .filter(publicacion_id__in=base.order_by().values('pk'), estado=Comentario.Estado.PUBLICADO)
                   .select_related('sentimiento').order_by())
    for comentario in comentarios:
        vigente = sentimiento_vigente(comentario)
        if vigente is None:
            sin_analisis += 1
        else:
            conteo[vigente.etiqueta] += 1
    return {
        'filas': barras([
            {'nombre': 'Positivo', 'total': conteo['positivo']},
            {'nombre': 'Neutral', 'total': conteo['neutral']},
            {'nombre': 'Negativo', 'total': conteo['negativo']},
        ]),
        'analizados': sum(conteo.values()),
        'sin_analisis': sin_analisis,
    }


# ---------------------------------------------------------------------------
# Portada
# ---------------------------------------------------------------------------


def resumen_portada(dias=30):
    """Lectura pública de la agenda reciente. None si todavía no hay publicaciones fechadas."""
    todas = Publicacion.objects.all()
    fin = ultimo_dia_con_datos(todas)
    if fin is None:
        return None
    inicio = fin - timedelta(days=dias - 1)
    comparacion = comparar_periodos(todas, inicio, fin)
    periodo = unicas(con_fecha_base(todas).filter(dia_base__gte=inicio, dia_base__lte=fin))
    territorio = cobertura_territorial(periodo)
    presentes = [tema for tema in comparacion['temas'] if tema['actual']]
    return {
        'total': todas.count(),
        'temas_presentes': len(presentes),
        'temas': presentes[:6],
        'inicio': inicio, 'fin': fin, 'dias': dias,
        'comparacion': comparacion,
        'territorio': territorio,
        'departamentos': [fila for fila in territorio['departamentos'] if fila['total']][:5],
        'semanas': serie_semanal(todas, fin),
    }
