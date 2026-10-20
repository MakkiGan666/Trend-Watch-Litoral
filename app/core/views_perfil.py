from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from .forms_perfil import PerfilForm
from .models import PerfilUsuario, Publicacion, PublicacionGuardada


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
        if accion == 'datos':
            datos = PerfilForm(request.POST, instance=request.user, prefix='datos')
            if datos.is_valid():
                with transaction.atomic():
                    datos.save()
                    PerfilUsuario.objects.update_or_create(usuario=request.user, defaults={
                        'fecha_nacimiento': datos.cleaned_data['fecha_nacimiento'],
                        'celular': datos.cleaned_data['celular'],
                    })
                messages.success(request, 'Tus datos se actualizaron correctamente.')
                return redirect('perfil')
        else:
            password = PasswordChangeForm(request.user, request.POST, prefix='password')
            if password.is_valid():
                user = password.save()
                update_session_auth_hash(request, user)
                messages.success(request, 'Tu contraseña se actualizó correctamente.')
                return redirect('perfil')
        status = 400
    guardados = None
    if seccion == 'guardados':
        guardados = Paginator(
            PublicacionGuardada.objects.filter(usuario=request.user).select_related('publicacion'), 12
        ).get_page(request.GET.get('pagina'))
    return render(request, 'core/perfil.html', {
        'seccion': seccion, 'datos_form': datos, 'password_form': password, 'guardados': guardados,
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
