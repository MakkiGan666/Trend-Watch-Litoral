"""Alta administrativa con rol fijo y auditoría transaccional."""
from django.contrib import messages
from django.contrib.admin.models import ADDITION, LogEntry
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.db import IntegrityError
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .forms import AdministradorCreationForm
from .roles import PERMISOS_ADMINISTRADOR, puede_gestionar_administradores
from .services.identidad import serializar_identidad


@login_required(login_url='login')
@require_http_methods(['GET', 'POST'])
@sensitive_post_parameters('password1', 'password2')
@never_cache
def gestion_administradores(request):
    if not puede_gestionar_administradores(request.user):
        raise PermissionDenied
    form = AdministradorCreationForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST':
        try:
            with serializar_identidad():
                if form.is_valid():
                    grupo = Group.objects.filter(name='Administrador').first()
                    permisos = set() if grupo is None else {
                        f'{p.content_type.app_label}.{p.codename}'
                        for p in grupo.permissions.select_related('content_type')
                    }
                    if permisos != PERMISOS_ADMINISTRADOR:
                        form.add_error(None, 'El rol Administrador no está configurado correctamente. Contactá al equipo técnico.')
                    else:
                        usuario = form.save(commit=False)
                        usuario.is_active = True
                        usuario.is_staff = True
                        usuario.is_superuser = False
                        usuario.save()
                        usuario.groups.set([grupo])
                        LogEntry.objects.log_actions(
                            user_id=request.user.pk,
                            queryset=type(usuario).objects.filter(pk=usuario.pk),
                            action_flag=ADDITION,
                            change_message='Cuenta creada desde Gestión de administradores; rol Administrador.',
                        )
                        messages.success(request, 'Administrador creado correctamente. Ya puede iniciar sesión.')
                        return redirect('gestion_administradores')
        except IntegrityError:
            # El bloque atómico revierte también el alta si falla su auditoría.
            form.add_error(None, 'No se pudo crear la cuenta. Revisá los datos e intentá nuevamente.')
    return render(request, 'core/gestion_administradores.html', {'form': form})
