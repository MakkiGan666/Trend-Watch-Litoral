"""Panel «Seguimiento de IA»: historial de ejecuciones de Gemini y Ollama (sólo administradores)."""
import json

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .fechas import ZONA_LOCAL
from .models import EjecucionIA, Publicacion
from .roles import puede_gestionar_administradores

POR_PAGINA = 30


def _exigir_administrador(request):
    if not puede_gestionar_administradores(request.user):
        raise PermissionDenied


class FiltrosSeguimiento(forms.Form):
    tarea = forms.ChoiceField(required=False, label='Tipo de análisis')
    proveedor = forms.ChoiceField(required=False, label='Proveedor')
    modelo = forms.ChoiceField(required=False, label='Modelo')
    estado = forms.ChoiceField(required=False, label='Estado',
                               choices=[('', 'Todos los estados'), *EjecucionIA.Estado.choices])
    desde = forms.DateField(required=False, label='Desde', widget=forms.DateInput(attrs={'type': 'date'}))
    hasta = forms.DateField(required=False, label='Hasta', widget=forms.DateInput(attrs={'type': 'date'}))
    publicacion = forms.IntegerField(required=False, min_value=1, label='Publicación (id)')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tareas = dict(EjecucionIA.Tarea.choices)
        registradas = EjecucionIA.objects.order_by().values_list('tarea', flat=True).distinct()
        self.fields['tarea'].choices = [('', 'Todos los análisis'), *[(t, tareas.get(t, t)) for t in sorted(set(tareas) | set(registradas))]]
        proveedores = sorted(set(EjecucionIA.objects.order_by().values_list('proveedor', flat=True).distinct()) | {'gemini', 'ollama'})
        self.fields['proveedor'].choices = [('', 'Todos los proveedores'), *[(p, p.capitalize()) for p in proveedores if p]]
        modelos = sorted(m for m in EjecucionIA.objects.order_by().values_list('modelo', flat=True).distinct() if m)
        self.fields['modelo'].choices = [('', 'Todos los modelos'), *[(m, m) for m in modelos]]

    def clean(self):
        datos = super().clean()
        if datos.get('desde') and datos.get('hasta') and datos['desde'] > datos['hasta']:
            raise forms.ValidationError('La fecha inicial no puede ser posterior a la final.')
        return datos


def _filtrar(datos):
    ejecuciones = EjecucionIA.objects.all()
    for campo in ('tarea', 'proveedor', 'modelo', 'estado'):
        if datos.get(campo):
            ejecuciones = ejecuciones.filter(**{campo: datos[campo]})
    if datos.get('desde'):
        ejecuciones = ejecuciones.filter(fecha__date__gte=datos['desde'])
    if datos.get('hasta'):
        ejecuciones = ejecuciones.filter(fecha__date__lte=datos['hasta'])
    if datos.get('publicacion'):
        pk = datos['publicacion']
        # También aparece en los lotes (clasificación territorial) por su lista de referencias.
        ids = [e.pk for e in EjecucionIA.objects.filter(entidad='lote').only('pk', 'referencias') if pk in (e.referencias or [])]
        ejecuciones = ejecuciones.filter(publicacion_id=pk) | ejecuciones.filter(pk__in=ids)
    return ejecuciones


@login_required(login_url='login')
@require_GET
@never_cache
def seguimiento_ia(request):
    _exigir_administrador(request)
    form = FiltrosSeguimiento(request.GET or None)
    valido = form.is_valid() if request.GET else True
    datos = form.cleaned_data if request.GET and valido else {}
    ejecuciones = _filtrar(datos) if valido else EjecucionIA.objects.none()
    resumen = dict(ejecuciones.order_by().values_list('estado').annotate(total=Count('pk')))
    pagina = Paginator(ejecuciones.defer('instrucciones', 'entrada', 'respuesta_original', 'resultado'),
                       POR_PAGINA).get_page(request.GET.get('pagina'))
    existentes = set(Publicacion.objects.filter(
        pk__in=[e.publicacion_id for e in pagina if e.publicacion_id]).values_list('pk', flat=True))
    parametros = request.GET.copy()
    parametros.pop('pagina', None)
    return render(request, 'core/seguimiento_ia.html', {
        'form': form, 'pagina': pagina, 'existentes': existentes,
        'total': sum(resumen.values()),
        'resumen': [(valor, etiqueta, resumen.get(valor, 0)) for valor, etiqueta in EjecucionIA.Estado.choices],
        'consulta': parametros.urlencode(),
    }, status=200 if valido else 400)


def _json_legible(valor):
    if valor in (None, ''):
        return ''
    if isinstance(valor, str):
        try:
            valor = json.loads(valor)
        except ValueError:
            return valor
    return json.dumps(valor, ensure_ascii=False, indent=2)


@login_required(login_url='login')
@require_GET
@never_cache
def detalle_ejecucion_ia(request, identificador):
    _exigir_administrador(request)
    ejecucion = get_object_or_404(EjecucionIA, identificador=identificador)
    publicacion = Publicacion.objects.filter(pk=ejecucion.publicacion_id).only('pk', 'titulo').first() if ejecucion.publicacion_id else None
    return render(request, 'core/seguimiento_ia_detalle.html', {
        'ejecucion': ejecucion,
        'publicacion': publicacion,
        'fecha_local': ejecucion.fecha.astimezone(ZONA_LOCAL),
        'respuesta_legible': _json_legible(ejecucion.respuesta_original),
        'resultado_legible': _json_legible(ejecucion.resultado),
        'entrada_legible': _json_legible(ejecucion.entrada),
        'etiquetas_asignadas': ejecucion.etiquetas_asignadas.select_related('etiqueta', 'publicacion').order_by('posicion'),
    })
