from collections import defaultdict

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Max, Min, Q
from django.db.models.functions import Coalesce, TruncDate, TruncMonth
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .fechas import ZONA_LOCAL
from .localidades import DEPARTAMENTOS, departamento_de_ubicacion
from .models import Categoria, Locacion, Publicacion
from .services.indicadores import ANALISIS_VALIDO, publicaciones_con_estado, resumen_publicaciones


class FiltrosDashboard(forms.Form):
    desde = forms.DateField(required=False, label='Desde', widget=forms.DateInput(attrs={'type': 'date'}))
    hasta = forms.DateField(required=False, label='Hasta', widget=forms.DateInput(attrs={'type': 'date'}))
    categoria = forms.ModelChoiceField(required=False, label='Categoría', empty_label='Todas las categorías', queryset=Categoria.objects.order_by('nombre_categoria', 'pk'))
    departamento = forms.ChoiceField(required=False, label='Departamento', choices=[('', 'Todos los departamentos'), *[(d['slug'], d['nombre']) for d in DEPARTAMENTOS], ('sin-identificar', 'Sin identificar')])
    fuente = forms.ChoiceField(required=False, label='Fuente')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['fuente'].choices = [('', 'Todas las fuentes'), *[(s, s) for s in Publicacion.objects.order_by('fuente').values_list('fuente', flat=True).distinct() if s]]

    def clean(self):
        datos = super().clean()
        if datos.get('desde') and datos.get('hasta') and datos['desde'] > datos['hasta']:
            raise forms.ValidationError('La fecha inicial no puede ser posterior a la final.')
        return datos


def barras(filas):
    maximo = max((f['total'] for f in filas), default=1) or 1
    return [{**f, 'ancho': round(f['total'] * 100 / maximo, 2)} for f in filas]


@login_required(login_url='login')
@require_GET
def dashboard(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    form = FiltrosDashboard(request.GET)
    valido = form.is_valid()
    publicaciones = Publicacion.objects.annotate(fecha_base=Coalesce('fecha_publicacion', 'fecha_captura')).annotate(dia_base=TruncDate('fecha_base', tzinfo=ZONA_LOCAL))
    # Ubicaciones legacy: usar el mismo catálogo territorial que Publicaciones.
    ubicaciones = defaultdict(list)
    for nombre in Locacion.objects.order_by().values_list('location', flat=True).distinct():
        slug = departamento_de_ubicacion(nombre)
        if slug:
            ubicaciones[slug].append(nombre)
    if valido:
        filtros = form.cleaned_data
        if filtros['desde']:
            publicaciones = publicaciones.filter(dia_base__gte=filtros['desde'])
        if filtros['hasta']:
            publicaciones = publicaciones.filter(dia_base__lte=filtros['hasta'])
        if filtros['categoria']:
            publicaciones = publicaciones.filter(temas__id_categoria=filtros['categoria'])
        if filtros['fuente']:
            publicaciones = publicaciones.filter(fuente=filtros['fuente'])
        slug = filtros['departamento']
        if slug == 'sin-identificar':
            publicaciones = publicaciones.exclude(departamento__in=[d['slug'] for d in DEPARTAMENTOS]).exclude(locacion__location__in=[n for lista in ubicaciones.values() for n in lista])
        elif slug:
            publicaciones = publicaciones.filter(Q(departamento=slug) | Q(locacion__location__in=ubicaciones[slug]))
    else:
        publicaciones = publicaciones.none()
    # Subconsulta de identidad evita duplicados por categorías o ubicaciones múltiples.
    ids = publicaciones.order_by().values('pk').distinct()
    base = Publicacion.objects.filter(pk__in=ids)
    resumen = resumen_publicaciones(base)
    categorias = list(base.order_by().values('temas__id_categoria__nombre_categoria').annotate(total=Count('pk', distinct=True)))
    categorias = barras([{'nombre': f['temas__id_categoria__nombre_categoria'] or 'Sin categoría asociada', 'total': f['total']} for f in categorias])
    fuentes = barras([{'nombre': f['fuente'] or 'Sin fuente', 'total': f['total']} for f in base.order_by().values('fuente').annotate(total=Count('pk')).order_by('-total', 'fuente')])
    por_departamento = defaultdict(set)
    conocidos = {d['slug']: d['nombre'] for d in DEPARTAMENTOS}
    for pk, slug in base.values_list('pk', 'departamento'):
        if slug in conocidos:
            por_departamento[slug].add(pk)
    for pk, nombre in Locacion.objects.filter(id_publicacion_api__in=base).values_list('id_publicacion_api', 'location'):
        slug = departamento_de_ubicacion(nombre)
        if slug:
            por_departamento[slug].add(pk)
    asociados = set().union(*por_departamento.values()) if por_departamento else set()
    departamentos = barras([{'nombre': d['nombre'], 'total': len(por_departamento[d['slug']])} for d in DEPARTAMENTOS] + [{'nombre': 'Sin identificar', 'total': resumen['total'] - len(asociados)}])
    datos = publicaciones_con_estado(base).filter(ANALISIS_VALIDO)
    sentimientos = barras([
        {'nombre': 'Positivo', 'total': datos.filter(polaridad_registrada__gt=0).count()},
        {'nombre': 'Neutral', 'total': datos.filter(polaridad_registrada=0).count()},
        {'nombre': 'Negativo', 'total': datos.filter(polaridad_registrada__lt=0).count()},
    ])
    fechadas = base.annotate(fecha_base=Coalesce('fecha_publicacion', 'fecha_captura'))
    extremos = fechadas.aggregate(primera=Min('fecha_base'), ultima=Max('fecha_base'))
    mensual = extremos['primera'] and (extremos['ultima'] - extremos['primera']).days > 120
    agrupador = TruncMonth('fecha_base', tzinfo=ZONA_LOCAL) if mensual else TruncDate('fecha_base', tzinfo=ZONA_LOCAL)
    serie = [{'fecha': x['periodo'].strftime('%m/%Y' if mensual else '%d/%m/%Y'), 'total': x['total']} for x in fechadas.annotate(periodo=agrupador).values('periodo').annotate(total=Count('pk')).order_by('periodo')]
    # Se muestran los períodos con registros, sin inventar observaciones entre ellos.
    maximo = max((x['total'] for x in serie), default=1)
    for i, fila in enumerate(serie):
        fila['x'] = format(30 + i * 640 / max(1, len(serie) - 1), '.2f')
        fila['y'] = format(190 - fila['total'] * 155 / maximo, '.2f')
    puntos = ' '.join(f'{30 + i * 640 / max(1, len(serie) - 1):.2f},{190 - x["total"] * 155 / maximo:.2f}' for i, x in enumerate(serie))
    return render(request, 'core/dashboard.html', {
        'filtros': form, 'resumen': resumen, 'categorias': categorias, 'fuentes': fuentes,
        'departamentos': departamentos, 'sentimientos': sentimientos, 'serie': serie,
        'puntos': puntos, 'mensual': mensual,
    }, status=200 if valido else 400)
