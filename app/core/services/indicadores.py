"""Lectura de indicadores reales; nunca ejecuta ingesta ni análisis de IA."""
from django.db.models import Count, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce

from core.models import Sentimiento


def publicaciones_con_estado(queryset):
    sentimientos = Sentimiento.objects.filter(id_publicacion_api=OuterRef('pk')).order_by('pk')
    cantidad = sentimientos.order_by().values('id_publicacion_api').annotate(total=Count('pk')).values('total')
    return queryset.annotate(
        cantidad_analisis=Coalesce(Subquery(cantidad), 0),
        polaridad_registrada=Subquery(sentimientos.values('polaridad')[:1]),
        confianza_registrada=Subquery(sentimientos.values('confianza')[:1]),
    )


ANALISIS_VALIDO = Q(cantidad_analisis=1, polaridad_registrada__gte=-1,
                   polaridad_registrada__lte=1, confianza_registrada__gte=0,
                   confianza_registrada__lte=1,
                   contenido_completo=True, contenido__regex=r'\S')


def resumen_publicaciones(queryset):
    total = queryset.count()
    fichas = queryset.filter(contenido_completo=False).count()
    completos = queryset.con_cuerpo_completo()
    cantidad_completos = completos.count()
    datos = publicaciones_con_estado(completos)
    analizadas = datos.filter(ANALISIS_VALIDO).count()
    pendientes = datos.filter(cantidad_analisis=0).count()
    return {
        'total': total,
        'articulos_completos': cantidad_completos,
        'fichas_rss': fichas,
        'sin_cuerpo_sin_ficha': total - fichas - cantidad_completos,
        'analizadas': analizadas,
        'pendientes': pendientes,
        'inconsistentes': cantidad_completos - analizadas - pendientes,
    }
