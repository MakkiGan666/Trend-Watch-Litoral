import re
from collections import defaultdict
from datetime import timedelta
from urllib.parse import urlencode

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Max, Min, Q
from django.db.models.functions import Coalesce, TruncDate, TruncMonth
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET

from .fechas import ZONA_LOCAL
from .localidades import DEPARTAMENTOS
from .models import (
    Categoria, ClicPublicacion, Comentario, Publicacion,
    ValoracionPublicacion,
)
from .roles import PERMISOS_PANEL
from .services import temas
from .services.indicadores import resumen_publicaciones
from .services.observatorio import (
    NOMBRES_DEPARTAMENTO, SIN_IDENTIFICAR, barras, cobertura_territorial, comparar_periodos,
    con_fecha_base, conteo_categorias, evolucion_mensual_temas, filtrar_departamento,
    filtrar_texto, hoy_local, sentimiento_comentarios, sentimiento_publicaciones,
    ubicaciones_por_departamento, ultimo_dia_con_datos, unicas,
)

PERIODOS_RAPIDOS = [
    ('', 'Todo el archivo'), ('7', 'Últimos 7 días'), ('30', 'Últimos 30 días'),
    ('90', 'Últimos 90 días'), ('365', 'Últimos 12 meses'),
]
# Sin fechas elegidas, la comparación usa los últimos 30 días con publicaciones.
DIAS_COMPARACION = 30


def fuente_visible(nombre):
    if re.fullmatch(r'El\s+Territorio(?:\s*\([^)]*\))?', nombre or '', re.I):
        return 'El Territorio'
    return nombre or 'Sin fuente'


class FiltrosDashboard(forms.Form):
    q = forms.CharField(required=False, max_length=150, label='Buscar en publicaciones', widget=forms.TextInput(attrs={'placeholder': 'Palabras del título o del texto', 'type': 'search'}))
    periodo = forms.ChoiceField(required=False, label='Período', choices=PERIODOS_RAPIDOS)
    desde = forms.DateField(required=False, label='Desde', widget=forms.DateInput(attrs={'type': 'date'}))
    hasta = forms.DateField(required=False, label='Hasta', widget=forms.DateInput(attrs={'type': 'date'}))
    categoria = forms.ModelChoiceField(required=False, label='Categoría', empty_label='Todas las categorías', queryset=Categoria.objects.order_by('nombre_categoria', 'pk'))
    departamento = forms.ChoiceField(required=False, label='Departamento', choices=[('', 'Todos los departamentos'), *[(d['slug'], d['nombre']) for d in DEPARTAMENTOS], (SIN_IDENTIFICAR, 'Sin identificar')])
    fuente = forms.ChoiceField(required=False, label='Fuente')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        nombres_fuente = Publicacion.objects.order_by().values_list('fuente', flat=True).distinct()
        self.fuentes_territorio = [nombre for nombre in nombres_fuente if fuente_visible(nombre) == 'El Territorio']
        fuentes = sorted({fuente_visible(nombre) for nombre in nombres_fuente if nombre}, key=str.casefold)
        self.fields['fuente'].choices = [('', 'Todas las fuentes'), *[(nombre, nombre) for nombre in fuentes]]

    def clean(self):
        datos = super().clean()
        if datos.get('periodo') and (datos.get('desde') or datos.get('hasta')):
            raise forms.ValidationError('Elegí un período rápido o fechas personalizadas, no ambos.')
        if datos.get('periodo'):
            datos['hasta'] = hoy_local()
            datos['desde'] = datos['hasta'] - timedelta(days=int(datos['periodo']) - 1)
        if datos.get('desde') and datos.get('hasta') and datos['desde'] > datos['hasta']:
            raise forms.ValidationError('La fecha inicial no puede ser posterior a la final.')
        return datos


def _filtrar(filtros, ubicaciones, fuentes_territorio, con_departamento=True):
    """Filtros que no dependen de la fecha; la fecha se aplica aparte para comparar períodos."""
    publicaciones = filtrar_texto(Publicacion.objects.all(), filtros['q'])
    if filtros['categoria']:
        publicaciones = publicaciones.filter(temas__id_categoria=filtros['categoria'])
    if filtros['fuente'] == 'El Territorio':
        publicaciones = publicaciones.filter(fuente__in=fuentes_territorio)
    elif filtros['fuente']:
        publicaciones = publicaciones.filter(fuente=filtros['fuente'])
    if con_departamento and filtros['departamento']:
        publicaciones = filtrar_departamento(publicaciones, filtros['departamento'], ubicaciones)
    return unicas(publicaciones)


def _en_periodo(publicaciones, filtros):
    fechadas = con_fecha_base(publicaciones)
    if filtros['desde']:
        fechadas = fechadas.filter(dia_base__gte=filtros['desde'])
    if filtros['hasta']:
        fechadas = fechadas.filter(dia_base__lte=filtros['hasta'])
    return unicas(fechadas)


def _url_panel(request, **cambios):
    """Misma consulta del panel con algunos filtros cambiados (para profundizar)."""
    parametros = request.GET.copy()
    for clave, valor in cambios.items():
        if valor in (None, ''):
            parametros.pop(clave, None)
        else:
            parametros[clave] = valor
    consulta = parametros.urlencode()
    return reverse('dashboard') + (f'?{consulta}' if consulta else '')


def _url_publicaciones(filtros, departamento=None, categoria=None):
    """Listado de gestión con los filtros equivalentes que admite Publicaciones."""
    departamento = departamento if departamento is not None else filtros.get('departamento')
    categoria = categoria if categoria is not None else (filtros.get('categoria').pk if filtros.get('categoria') else None)
    parametros = {
        'q': filtros.get('q') or '',
        'localidad': '__missing' if departamento == SIN_IDENTIFICAR else (departamento or ''),
        'categoria': categoria or '',
    }
    consulta = urlencode({k: v for k, v in parametros.items() if v})
    return reverse('publicaciones') + (f'?{consulta}' if consulta else '')


def _tematica(base, sin_fecha, filtros, total):
    """Etiquetas temáticas del período filtrado: frecuencia, alza, territorio y tono.

    Usa las etiquetas de IA cuando existen; mientras tanto, las palabras clave del texto.
    La comparación usa el período elegido (o los últimos 30 días con datos) contra el
    período anterior de igual duración.
    """
    if not total:
        return None
    origen = temas.origen_preferido()
    frecuentes = barras(temas.frecuencia_etiquetas(base, limite=10, origen=origen))
    for fila in frecuentes:
        fila['url'] = reverse('publicaciones_etiqueta', args=[fila['slug']])
    alza = None
    fin = filtros.get('hasta') or ultimo_dia_con_datos(base)
    if fin:
        inicio = filtros.get('desde') or fin - timedelta(days=DIAS_COMPARACION - 1)
        alza = temas.etiquetas_en_alza(sin_fecha, inicio, fin, limite=8, origen=origen)
    return {
        'origen': origen, 'origen_nombre': temas.etiqueta_de_origen(origen),
        'frecuentes': frecuentes, 'alza': alza,
        'por_departamento': temas.etiquetas_por_departamento(base, origen=origen)[:8],
        'negativas': temas.sentimiento_por_etiqueta(base, limite=8, origen=origen),
    }


@login_required(login_url='login')
@require_GET
def dashboard(request):
    if not request.user.has_perms(PERMISOS_PANEL):
        raise PermissionDenied
    form = FiltrosDashboard(request.GET)
    valido = form.is_valid()
    ubicaciones = ubicaciones_por_departamento()
    if valido:
        filtros = form.cleaned_data
        sin_fecha = _filtrar(filtros, ubicaciones, form.fuentes_territorio)
        base = _en_periodo(sin_fecha, filtros)
    else:
        filtros = {}
        sin_fecha = base = Publicacion.objects.none()
    resumen = resumen_publicaciones(base)
    ids = base.values('pk')

    categorias = barras(conteo_categorias(base))
    for fila in categorias:
        if fila['id'] is not None:
            fila['url'] = _url_panel(request, categoria=fila['id'])
            fila['url_publicaciones'] = _url_publicaciones(filtros, categoria=fila['id'])
    totales_fuente = defaultdict(int)
    for fila in base.order_by().values('fuente').annotate(total=Count('pk')):
        totales_fuente[fuente_visible(fila['fuente'])] += fila['total']
    fuentes = barras([
        {'nombre': nombre, 'total': total}
        for nombre, total in sorted(totales_fuente.items(), key=lambda item: (-item[1], item[0]))
    ])

    # El ranking territorial ignora el filtro de departamento para poder comparar
    # el departamento elegido con el resto; los demás filtros sí se aplican.
    seleccionado = filtros.get('departamento', '')
    base_territorio = _en_periodo(_filtrar(filtros, ubicaciones, form.fuentes_territorio, con_departamento=False), filtros) if seleccionado else base
    territorio = cobertura_territorial(base_territorio)
    departamentos = territorio['departamentos']
    for fila in departamentos:
        fila['url'] = _url_panel(request, departamento=fila['slug'])
        fila['seleccionado'] = fila['slug'] == seleccionado
    territorio['url_sin_identificar'] = _url_panel(request, departamento=SIN_IDENTIFICAR)
    foco_territorial = None
    if seleccionado in NOMBRES_DEPARTAMENTO and resumen['total']:
        datos = next(d for d in DEPARTAMENTOS if d['slug'] == seleccionado)
        foco_territorial = {
            'nombre': datos['nombre'], 'municipios': datos['municipios'], 'total': resumen['total'],
            'temas': [c for c in categorias if c['id'] is not None][:5],
            'url_publica': reverse('localidad', args=[seleccionado]),
            'url_publicaciones': _url_publicaciones(filtros),
        }

    comparacion = None
    if resumen['total']:
        fin = filtros['hasta'] or ultimo_dia_con_datos(base)
        if fin:
            inicio = filtros['desde'] or fin - timedelta(days=DIAS_COMPARACION - 1)
            comparacion = comparar_periodos(sin_fecha, inicio, fin)
            comparacion['automatica'] = not (filtros['desde'] and filtros['hasta'])
            for tema in comparacion['temas']:
                tema['url'] = _url_panel(request, categoria=tema['id'])

    tematica = _tematica(base, sin_fecha, filtros, resumen['total'])

    sentimientos = sentimiento_publicaciones(base)
    tono_comentarios = sentimiento_comentarios(base)

    valoraciones = ValoracionPublicacion.objects.filter(publicacion_id__in=ids)
    conteo_valoraciones = {
        fila['sentimiento']: fila['total']
        for fila in valoraciones.values('sentimiento').annotate(total=Count('pk'))
    }
    valoraciones_lectores = barras([
        {'nombre': nombre, 'total': conteo_valoraciones.get(codigo, 0)}
        for codigo, nombre in ValoracionPublicacion.Sentimiento.choices
    ])
    comentarios = Comentario.objects.filter(publicacion_id__in=ids).aggregate(
        publicados=Count('pk', filter=Q(estado=Comentario.Estado.PUBLICADO)),
        pendientes=Count('pk', filter=Q(estado=Comentario.Estado.PENDIENTE)),
        rechazados=Count('pk', filter=Q(estado=Comentario.Estado.RECHAZADO)),
    )
    comentarios_lectores = barras([
        {'nombre': 'Publicados', 'total': comentarios['publicados']},
        {'nombre': 'Pendientes', 'total': comentarios['pendientes']},
        {'nombre': 'Rechazados', 'total': comentarios['rechazados']},
    ])
    participacion = {
        'clics': ClicPublicacion.objects.filter(publicacion_id__in=ids).count(),
        'valoraciones': sum(conteo_valoraciones.values()),
        'comentarios_publicados': comentarios['publicados'],
        'comentarios_pendientes': comentarios['pendientes'],
        'comentarios_total': sum(comentarios.values()),
    }

    fechadas = base.annotate(fecha_base=Coalesce('fecha_publicacion', 'fecha_captura'))
    extremos = fechadas.aggregate(primera=Min('fecha_base'), ultima=Max('fecha_base'))
    mensual = extremos['primera'] and (extremos['ultima'] - extremos['primera']).days > 120
    agrupador = TruncMonth('fecha_base', tzinfo=ZONA_LOCAL) if mensual else TruncDate('fecha_base', tzinfo=ZONA_LOCAL)
    periodos = list(fechadas.annotate(periodo=agrupador).values('periodo').annotate(total=Count('pk')).order_by('periodo'))
    posiciones = [x['periodo'].year * 12 + x['periodo'].month if mensual else x['periodo'].toordinal() for x in periodos]
    serie = [{'fecha': x['periodo'].strftime('%m/%Y' if mensual else '%d/%m/%Y'), 'total': x['total']} for x in periodos]
    # Se muestran los períodos con registros, sin inventar observaciones entre ellos.
    maximo = max((x['total'] for x in serie), default=1)
    for i, fila in enumerate(serie):
        fila['x'] = format(30 + (posiciones[i] - posiciones[0]) * 640 / max(1, posiciones[-1] - posiciones[0]), '.2f')
        fila['y'] = format(190 - fila['total'] * 155 / maximo, '.2f')
    puntos = ' '.join(f'{fila["x"]},{fila["y"]}' for fila in serie)

    filtros_activos = [
        (form.fields[nombre].label, valor) for nombre, valor in (
            ('q', filtros.get('q')),
            ('periodo', dict(PERIODOS_RAPIDOS).get(filtros.get('periodo')) if filtros.get('periodo') else ''),
            ('desde', filtros.get('desde') if not filtros.get('periodo') else ''),
            ('hasta', filtros.get('hasta') if not filtros.get('periodo') else ''),
            ('categoria', filtros.get('categoria')),
            ('departamento', dict(form.fields['departamento'].choices).get(seleccionado) if seleccionado else ''),
            ('fuente', filtros.get('fuente')),
        ) if valor
    ]
    return render(request, 'core/dashboard.html', {
        'filtros': form, 'resumen': resumen, 'categorias': categorias, 'fuentes': fuentes,
        'departamentos': departamentos, 'sentimientos': sentimientos, 'serie': serie,
        'puntos': puntos, 'mensual': mensual, 'participacion': participacion,
        'valoraciones_lectores': valoraciones_lectores,
        'comentarios_lectores': comentarios_lectores,
        'territorio': territorio, 'foco_territorial': foco_territorial,
        'departamento_seleccionado': seleccionado,
        'comparacion': comparacion, 'evolucion_temas': evolucion_mensual_temas(base),
        'tono_comentarios': tono_comentarios,
        'temas_presentes': sum(1 for fila in categorias if fila['id'] is not None),
        'filtros_activos': filtros_activos,
        'tematica': tematica,
        'url_publicaciones': _url_publicaciones(filtros),
    }, status=200 if valido else 400)
