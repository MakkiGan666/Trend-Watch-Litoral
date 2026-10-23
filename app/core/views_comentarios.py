from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from .forms import ComentarioForm
from .models import Comentario, Publicacion


def contexto_comentarios(request, publicacion):
    pagina = Paginator(publicacion.comentarios.select_related('autor'), 10).get_page(
        request.GET.get('pagina_comentarios')
    )
    return {
        'comentarios_pagina': pagina,
        'comentario_form': ComentarioForm(),
        'puede_moderar_comentarios': request.user.has_perm('core.delete_comentario'),
    }


def _pagina(request):
    try:
        return max(1, int(request.POST.get('pagina_comentarios', request.GET.get('pagina_comentarios', 1))))
    except (ValueError, TypeError):
        return 1


def _destino(publicacion_id, pagina=1, comentario_id=None):
    ancla = f'comentario-{comentario_id}' if comentario_id else 'comentarios'
    return reverse('noticia', args=[publicacion_id]) + f'?pagina_comentarios={pagina}#{ancla}'


@require_POST
@login_required(login_url='login')
def crear_comentario(request, pk):
    publicacion = get_object_or_404(Publicacion, pk=pk)
    form = ComentarioForm(request.POST)
    if form.is_valid():
        comentario = form.save(commit=False)
        comentario.publicacion = publicacion
        comentario.autor = request.user
        comentario.save()
        messages.success(request, 'Comentario publicado.')
        return redirect(_destino(pk, comentario_id=comentario.pk))
    return render(request, 'core/comentario_form.html', {
        'form': form, 'publicacion': publicacion, 'titulo': 'Publicar comentario',
        'pagina_comentarios': 1,
    }, status=400)


@require_http_methods(['GET', 'POST'])
@login_required(login_url='login')
def editar_comentario(request, pk):
    comentario = get_object_or_404(Comentario.objects.select_related('publicacion').defer(
        'publicacion__titulo_busqueda', 'publicacion__contenido_busqueda',
    ), pk=pk)
    if comentario.autor_id != request.user.pk:
        raise PermissionDenied
    form = ComentarioForm(request.POST if request.method == 'POST' else None, instance=comentario)
    if request.method == 'POST' and form.is_valid():
        comentario = form.save(commit=False)
        comentario.fecha_edicion = timezone.now()
        comentario.save(update_fields=['texto', 'fecha_edicion'])
        messages.success(request, 'Comentario actualizado.')
        return redirect(_destino(comentario.publicacion_id, _pagina(request), comentario.pk))
    return render(request, 'core/comentario_form.html', {
        'form': form, 'comentario': comentario, 'publicacion': comentario.publicacion,
        'titulo': 'Editar comentario', 'pagina_comentarios': _pagina(request),
    }, status=400 if request.method == 'POST' else 200)


@require_POST
@login_required(login_url='login')
def eliminar_comentario(request, pk):
    comentario = get_object_or_404(Comentario, pk=pk)
    if comentario.autor_id != request.user.pk and not request.user.has_perm('core.delete_comentario'):
        raise PermissionDenied
    publicacion_id = comentario.publicacion_id
    comentario.delete()
    messages.success(request, 'Comentario eliminado.')
    return redirect(_destino(publicacion_id, _pagina(request)))
