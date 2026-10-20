from django import forms
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from .models import Publicacion, ValoracionPublicacion


class ValoracionForm(forms.Form):
    sentimiento = forms.ChoiceField(choices=[*ValoracionPublicacion.Sentimiento.choices, ('retirar', 'Retirar')])


def contexto_valoraciones(request, publicacion):
    valoraciones = publicacion.valoraciones.all()
    totales = dict(valoraciones.values('sentimiento').annotate(total=Count('pk')).values_list('sentimiento', 'total'))
    propia = valoraciones.filter(usuario=request.user).values_list('sentimiento', flat=True).first() if request.user.is_authenticated else None
    return {
        'valoraciones_opciones': [
            {'valor': valor, 'etiqueta': etiqueta, 'total': totales.get(valor, 0), 'seleccionada': propia == valor}
            for valor, etiqueta in ValoracionPublicacion.Sentimiento.choices
        ],
        'valoraciones_total': sum(totales.values()),
        'valoracion_propia': propia,
    }


@require_POST
@login_required(login_url='login')
def valorar_noticia(request, pk):
    form = ValoracionForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest('Elegí Positivo, Neutral o Negativo, o retirá tu valoración.')
    sentimiento = form.cleaned_data['sentimiento']
    with transaction.atomic():
        # Serializa cambios/retiros simultáneos de la misma noticia; la restricción
        # de unicidad también protege frente a escritores que no tomen este bloqueo.
        publicacion = get_object_or_404(Publicacion.objects.select_for_update(), pk=pk)
        if sentimiento == 'retirar':
            ValoracionPublicacion.objects.filter(publicacion=publicacion, usuario=request.user).delete()
        else:
            ValoracionPublicacion.objects.update_or_create(
                publicacion=publicacion, usuario=request.user,
                defaults={'sentimiento': sentimiento},
            )
    return redirect(reverse('noticia', args=[pk]) + '#valoraciones')
