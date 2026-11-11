"""Inteligencia temática a partir de las etiquetas de las publicaciones.

Consultas verificables sobre datos existentes (no ejecuta IA ni escribe nada):
- filtrar por una o varias etiquetas (todas deben estar presentes);
- publicaciones relacionadas por coincidencia de etiquetas;
- etiquetas más frecuentes y co-ocurrentes;
- etiquetas en alza comparando dos períodos de igual duración;
- etiquetas por departamento (sólo con `Publicacion.departamento` identificado);
- sentimiento por etiqueta (sólo con análisis de sentimiento válidos);
- evolución semanal de una etiqueta.

`origen` acota a las etiquetas de IA (`'ia'`), a las léxicas (`'lexico'`) o a
ambas (None). `origen_preferido()` elige IA cuando ya hay etiquetas de IA y
léxico mientras tanto, para que los paneles digan siempre de dónde salen.
"""
import math
from collections import defaultdict
from datetime import timedelta

from django.db.models import Avg, Count, Q

from core.models import Etiqueta, Publicacion, PublicacionEtiqueta, Sentimiento
from core.services.observatorio import NOMBRES_DEPARTAMENTO, con_fecha_base, variacion

IA = PublicacionEtiqueta.Origen.IA
LEXICO = PublicacionEtiqueta.Origen.LEXICO
MAX_ETIQUETAS_FILTRO = 5
# Una etiqueta presente en más publicaciones que esto no sirve para relacionar noticias.
MAX_FRECUENCIA_RELACION = 400


def asociaciones(origen=None):
    qs = PublicacionEtiqueta.objects.all()
    return qs.filter(origen=origen) if origen else qs


def origen_preferido():
    return IA if PublicacionEtiqueta.objects.filter(origen=IA).exists() else LEXICO


def etiqueta_de_origen(origen):
    return 'Etiquetas temáticas (IA)' if origen == IA else 'Palabras clave del texto' if origen == LEXICO else 'Etiquetas'


def filtrar_por_etiquetas(queryset, slugs, origen=None):
    """Publicaciones que tienen *todas* las etiquetas indicadas (sin filas duplicadas)."""
    for slug in list(dict.fromkeys(slugs))[:MAX_ETIQUETAS_FILTRO]:
        queryset = queryset.filter(pk__in=asociaciones(origen).filter(etiqueta__slug=slug).values('publicacion_id'))
    return queryset


def frecuencia_etiquetas(publicaciones, limite=10, origen=None, excluir=()):
    """[{'slug', 'nombre', 'total'}]: publicaciones distintas por etiqueta, de mayor a menor."""
    filas = (asociaciones(origen).filter(publicacion_id__in=publicaciones.order_by().values('pk'))
             .exclude(etiqueta__slug__in=list(excluir))
             .values('etiqueta__slug', 'etiqueta__nombre')
             .annotate(total=Count('publicacion_id', distinct=True))
             .order_by('-total', 'etiqueta__nombre')[:limite])
    return [{'slug': f['etiqueta__slug'], 'nombre': f['etiqueta__nombre'], 'total': f['total']} for f in filas]


def _conteo_por_etiqueta(publicaciones, origen):
    return {
        f['etiqueta_id']: f['total'] for f in
        asociaciones(origen).filter(publicacion_id__in=publicaciones.order_by().values('pk'))
        .values('etiqueta_id').annotate(total=Count('publicacion_id', distinct=True))
    }


def _en_rango(queryset, inicio, fin):
    return con_fecha_base(queryset).filter(dia_base__gte=inicio, dia_base__lte=fin)


def etiquetas_en_alza(queryset, inicio, fin, limite=10, minimo=3, origen=None):
    """Compara [inicio, fin] con el período anterior de igual duración.

    Sólo incluye etiquetas con al menos `minimo` publicaciones en el período actual y
    más que en el anterior. `variacion` es None cuando no había base de comparación
    (etiqueta nueva en el período): no se inventa un porcentaje.
    """
    dias = (fin - inicio).days + 1
    anterior_fin = inicio - timedelta(days=1)
    anterior_inicio = anterior_fin - timedelta(days=dias - 1)
    actual = _conteo_por_etiqueta(_en_rango(queryset, inicio, fin), origen)
    previo = _conteo_por_etiqueta(_en_rango(queryset, anterior_inicio, anterior_fin), origen)
    candidatas = [(eid, n, previo.get(eid, 0)) for eid, n in actual.items() if n >= minimo and n > previo.get(eid, 0)]
    candidatas.sort(key=lambda c: (-(c[1] - c[2]), -c[1], c[0]))
    candidatas = candidatas[:limite]
    nombres = dict(Etiqueta.objects.filter(pk__in=[c[0] for c in candidatas]).values_list('pk', 'nombre'))
    slugs = dict(Etiqueta.objects.filter(pk__in=[c[0] for c in candidatas]).values_list('pk', 'slug'))
    return {
        'periodo': (inicio, fin), 'anterior': (anterior_inicio, anterior_fin), 'origen': origen,
        'etiquetas': [
            {'slug': slugs[eid], 'nombre': nombres[eid], 'actual': n, 'anterior': p,
             'diferencia': n - p, 'variacion': variacion(n, p)}
            for eid, n, p in candidatas
        ],
    }


def etiquetas_por_departamento(publicaciones, por_departamento=3, minimo=2, origen=None):
    """{slug_departamento: {'nombre', 'etiquetas': [...]}} sólo con departamentos identificados."""
    filas = (asociaciones(origen)
             .filter(publicacion_id__in=publicaciones.exclude(departamento='').order_by().values('pk'))
             .values('publicacion__departamento', 'etiqueta__slug', 'etiqueta__nombre')
             .annotate(total=Count('publicacion_id', distinct=True))
             .filter(total__gte=minimo)
             .order_by('publicacion__departamento', '-total', 'etiqueta__nombre'))
    resultado = {}
    for fila in filas:
        departamento = fila['publicacion__departamento']
        if departamento not in NOMBRES_DEPARTAMENTO:
            continue  # valor fuera del catálogo de los 17 departamentos: no se interpreta
        grupo = resultado.setdefault(departamento, {'slug': departamento, 'nombre': NOMBRES_DEPARTAMENTO[departamento], 'etiquetas': []})
        if len(grupo['etiquetas']) < por_departamento:
            grupo['etiquetas'].append({'slug': fila['etiqueta__slug'], 'nombre': fila['etiqueta__nombre'], 'total': fila['total']})
    return sorted(resultado.values(), key=lambda g: (-sum(e['total'] for e in g['etiquetas']), g['nombre']))


def departamentos_de_etiqueta(publicaciones, slug, origen=None):
    """¿Qué departamentos concentran publicaciones con esta etiqueta? (sólo identificados)."""
    filas = (filtrar_por_etiquetas(publicaciones, [slug], origen).exclude(departamento='')
             .order_by().values('departamento').annotate(total=Count('pk')).order_by('-total', 'departamento'))
    return [{'slug': f['departamento'], 'nombre': NOMBRES_DEPARTAMENTO[f['departamento']], 'total': f['total']}
            for f in filas if f['departamento'] in NOMBRES_DEPARTAMENTO]


def sentimiento_por_etiqueta(publicaciones, limite=10, minimo=3, origen=None):
    """Etiquetas con más publicaciones de sentimiento negativo (polaridad < -0.05).

    Sólo cuenta publicaciones con un único análisis de sentimiento en rango válido.
    """
    validas = (Sentimiento.objects.filter(id_publicacion_api__in=publicaciones.order_by().values('pk'),
                                          polaridad__gte=-1, polaridad__lte=1, confianza__gte=0, confianza__lte=1)
               .values('id_publicacion_api').annotate(n=Count('pk')).filter(n=1).values('id_publicacion_api'))
    filas = (asociaciones(origen).filter(publicacion_id__in=validas)
             .values('etiqueta__slug', 'etiqueta__nombre')
             .annotate(total=Count('publicacion_id', distinct=True),
                       negativas=Count('publicacion_id', distinct=True, filter=Q(publicacion__sentimiento__polaridad__lt=-0.05)),
                       polaridad=Avg('publicacion__sentimiento__polaridad'))
             .filter(total__gte=minimo, negativas__gt=0)
             .order_by('-negativas', 'polaridad', 'etiqueta__nombre')[:limite])
    return [{'slug': f['etiqueta__slug'], 'nombre': f['etiqueta__nombre'], 'total': f['total'],
             'negativas': f['negativas'], 'proporcion': round(f['negativas'] * 100 / f['total']),
             'polaridad': round(f['polaridad'], 2)} for f in filas]


def evolucion_etiqueta(publicaciones, slug, fin, semanas=8, origen=None):
    """Publicaciones por semana con la etiqueta; semanas sin publicaciones valen 0 (observado, no inventado)."""
    inicio = fin - timedelta(days=semanas * 7 - 1)
    dias = (_en_rango(filtrar_por_etiquetas(publicaciones, [slug], origen), inicio, fin)
            .values('dia_base').annotate(total=Count('pk')))
    conteo = defaultdict(int)
    for fila in dias:
        conteo[(fila['dia_base'] - inicio).days // 7] += fila['total']
    return [{'desde': inicio + timedelta(days=7 * i), 'hasta': inicio + timedelta(days=7 * i + 6), 'total': conteo[i]}
            for i in range(semanas)]


def etiquetas_coocurrentes(publicaciones, slugs, limite=8, origen=None):
    """Etiquetas que más aparecen junto a las elegidas (para combinar filtros)."""
    return frecuencia_etiquetas(filtrar_por_etiquetas(publicaciones, slugs, origen), limite=limite,
                                origen=origen, excluir=slugs)


def publicaciones_relacionadas(publicacion, limite=4, minimo_comunes=2):
    """Otras publicaciones con más etiquetas en común, ponderadas por rareza (IDF).

    Prefiere las etiquetas de IA de la noticia; si no tiene, usa las léxicas.
    Devuelve [(Publicacion, [nombres de etiquetas en común])].
    """
    propias = list(publicacion.etiquetas.all())
    if any(r.origen == IA for r in propias):
        propias = [r for r in propias if r.origen == IA]
        minimo_comunes = 1 if len(propias) <= 3 else minimo_comunes
    ids = {r.etiqueta_id for r in propias}
    if not ids:
        return []
    frecuencia = dict(PublicacionEtiqueta.objects.filter(etiqueta_id__in=ids).values('etiqueta_id')
                      .annotate(n=Count('publicacion_id', distinct=True)).values_list('etiqueta_id', 'n'))
    utiles = [eid for eid, n in frecuencia.items() if 1 < n <= MAX_FRECUENCIA_RELACION]
    if not utiles:
        return []
    total = Publicacion.objects.count() or 1
    puntaje, comunes = defaultdict(float), defaultdict(set)
    for pub_id, eid in (PublicacionEtiqueta.objects.filter(etiqueta_id__in=utiles).exclude(publicacion_id=publicacion.pk)
                        .values_list('publicacion_id', 'etiqueta_id').distinct()):
        if eid not in comunes[pub_id]:
            comunes[pub_id].add(eid)
            puntaje[pub_id] += math.log(total / frecuencia[eid])
    elegidas = sorted((p for p in comunes if len(comunes[p]) >= minimo_comunes),
                      key=lambda p: (-puntaje[p], -p))[:limite * 3]
    if not elegidas:
        return []
    nombres = dict(Etiqueta.objects.filter(pk__in=utiles).values_list('pk', 'nombre'))
    publicaciones = Publicacion.objects.in_bulk(elegidas)
    titulos = {publicacion.titulo.strip().casefold()}
    resultado = []
    for pub_id in elegidas:
        relacionada = publicaciones.get(pub_id)
        clave = relacionada.titulo.strip().casefold() if relacionada else None
        if relacionada is None or clave in titulos:
            continue  # misma noticia publicada dos veces
        titulos.add(clave)
        resultado.append((relacionada, sorted((nombres[e] for e in comunes[pub_id]), key=str.casefold)))
        if len(resultado) == limite:
            break
    return resultado
