from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from .forms_perfil import PerfilForm
from .services.identidad import serializar_identidad
from .models import PerfilUsuario, Publicacion, PublicacionGuardada, ValoracionPublicacion


@login_required(login_url='login')
@require_http_methods(['GET', 'POST'])
def perfil(request, seccion='datos'):
    perfil_actual = PerfilUsuario.objects.filter(usuario=request.user).first()
    initial = {
        'fecha_nacimiento': perfil_actual.fecha_nacimiento if perfil_actual else None,
        'celular': perfil_actual.celular if perfil_actual else '',
    }
    datos = PerfilForm(instance=request.user, initial=initial, prefix='datos')
    password = PasswordChangeForm(request.user, prefix='password')
    status = 200
    if request.method == 'POST':
        accion = request.POST.get('accion')
        if seccion != 'datos' or accion not in ('datos', 'password'):
            return redirect('perfil')
        # Releer bajo bloqueo antes de validar: request.user puede tener un hash viejo.
        # La fila queda bloqueada hasta terminar la escritura, incluso ante una
        # rotación externa que solo haga UPDATE y no use select_for_update().
        # Para datos: identidad global antes de fila; contraseña no cambia identidad.
        with serializar_identidad() if accion == 'datos' else transaction.atomic():
            usuario_actual = get_object_or_404(
                get_user_model().objects.select_for_update(), pk=request.user.pk,
            )
            if not usuario_actual.is_active:
                raise PermissionDenied
            if accion == 'datos':
                datos = PerfilForm(request.POST, instance=usuario_actual, prefix='datos')
                if datos.is_valid():
                    # Meta.fields limita la entrada, no las columnas de User.save().
                    # No reescribir contraseña/flags ni campos que el lector no editó.
                    campos = [campo for campo in ('first_name', 'last_name', 'email')
                              if campo in datos.changed_data]
                    usuario = datos.save(commit=False)
                    if campos:
                        usuario.save(update_fields=campos)
                    PerfilUsuario.objects.update_or_create(usuario=usuario_actual, defaults={
                        'fecha_nacimiento': datos.cleaned_data['fecha_nacimiento'],
                        'celular': datos.cleaned_data['celular'],
                    })
                    messages.success(request, 'Tus datos se actualizaron correctamente.')
                    return redirect('perfil')
            else:
                password = PasswordChangeForm(usuario_actual, request.POST, prefix='password')
                if password.is_valid():
                    user = password.save(commit=False)
                    user.save(update_fields=['password'])
                    update_session_auth_hash(request, user)
                    messages.success(request, 'Tu contraseña se actualizó correctamente.')
                    return redirect('perfil')
        status = 400
    guardados = None
    recomendaciones = []
    if seccion == 'guardados':
        guardados = Paginator(
            PublicacionGuardada.objects.filter(usuario=request.user).select_related('publicacion').defer(
                'publicacion__titulo_busqueda', 'publicacion__contenido_busqueda',
            ), 12
        ).get_page(request.GET.get('pagina'))
        guardados_ids = list(PublicacionGuardada.objects.filter(usuario=request.user).values_list('publicacion_id', flat=True))
        positivos_ids = list(ValoracionPublicacion.objects.filter(
            usuario=request.user, sentimiento=ValoracionPublicacion.Sentimiento.POSITIVO,
        ).values_list('publicacion_id', flat=True))
        preferidos_ids = set(guardados_ids + positivos_ids)
        if preferidos_ids:
            negativos_ids = list(ValoracionPublicacion.objects.filter(
                usuario=request.user, sentimiento=ValoracionPublicacion.Sentimiento.NEGATIVO,
            ).values_list('publicacion_id', flat=True))
            categorias_ids = list(Publicacion.objects.filter(
                pk__in=preferidos_ids, temas__id_categoria_id__isnull=False,
            ).values_list('temas__id_categoria_id', flat=True).distinct())
            departamentos = list(Publicacion.objects.filter(pk__in=preferidos_ids).exclude(
                departamento='',
            ).values_list('departamento', flat=True).distinct())
            coincidencias = Q()
            if categorias_ids:
                coincidencias |= Q(temas__id_categoria_id__in=categorias_ids)
            if departamentos:
                coincidencias |= Q(departamento__in=departamentos)
            if coincidencias:
                recomendaciones = list(Publicacion.objects.filter(coincidencias).exclude(
                    pk__in=preferidos_ids,
                ).exclude(pk__in=negativos_ids).annotate(
                    afinidad=Count('temas__id_categoria_id',
                                   filter=Q(temas__id_categoria_id__in=categorias_ids), distinct=True),
                    proximidad=Case(When(departamento__in=departamentos, then=Value(1)),
                                    default=Value(0), output_field=IntegerField()),
                ).order_by(
                    '-afinidad', '-proximidad', '-fecha_publicacion', '-pk',
                ).distinct()[:3])
    return render(request, 'core/perfil.html', {
        'seccion': seccion, 'datos_form': datos, 'password_form': password,
        'guardados': guardados, 'recomendaciones': recomendaciones,
    }, status=status)


@login_required(login_url='login')
@require_POST
def guardar_publicacion(request, pk):
    publicacion = get_object_or_404(Publicacion, pk=pk)
    accion = request.POST.get('accion')
    if accion == 'guardar':
        PublicacionGuardada.objects.get_or_create(usuario=request.user, publicacion=publicacion)
    elif accion == 'quitar':
        PublicacionGuardada.objects.filter(usuario=request.user, publicacion=publicacion).delete()
    else:
        return redirect('noticia', pk=pk)
    if request.POST.get('origen') == 'guardados':
        return redirect('mis_guardados')
    return redirect('noticia', pk=pk)
