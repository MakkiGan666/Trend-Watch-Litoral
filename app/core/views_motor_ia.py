"""Panel «Motor de Inteligencia Artificial»: elección del motor, respaldo y estado de conexión."""
from django.contrib import messages
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from .forms_motor_ia import ConfiguracionIAForm
from .models import ConfiguracionIA
from .roles import puede_gestionar_administradores
from .services.ia.base import PROVEEDOR_GEMINI, PROVEEDOR_OLLAMA, PROVEEDORES
from .services.ia.gestor import GestorIA, configuracion_actual
from .services.ia.ollama import config_ollama

ETIQUETAS_MOTOR = {PROVEEDOR_GEMINI: 'Gemini', PROVEEDOR_OLLAMA: 'Llama 3.1'}


def _exigir_administrador(request):
    if not puede_gestionar_administradores(request.user):
        raise PermissionDenied


def _guardar_configuracion(usuario, motor, respaldo):
    with transaction.atomic():
        fila, _ = ConfiguracionIA.objects.select_for_update().get_or_create(pk=ConfiguracionIA.PK)
        fila.motor_principal = motor
        fila.respaldo_automatico = respaldo
        fila.actualizado_por = usuario
        fila.save()
        LogEntry.objects.log_actions(
            user_id=usuario.pk,
            queryset=ConfiguracionIA.objects.filter(pk=fila.pk),
            action_flag=CHANGE,
            change_message=(f'Motor de IA: principal {ETIQUETAS_MOTOR[motor]}; '
                            f'respaldo automático {"activado" if respaldo else "desactivado"}.'),
        )


@login_required(login_url='login')
@require_http_methods(['GET', 'POST'])
@never_cache
def motor_ia(request):
    _exigir_administrador(request)
    gestor = GestorIA()
    if request.method == 'POST':
        form = ConfiguracionIAForm(request.POST)
        if form.is_valid():
            try:
                _guardar_configuracion(request.user, form.cleaned_data['motor_principal'],
                                       form.cleaned_data['respaldo_automatico'])
            except DatabaseError:
                # Típico si la migración de ConfiguracionIA todavía no se aplicó.
                form.add_error(None, 'No se pudo guardar la configuración. Verificá que las migraciones estén aplicadas.')
            else:
                messages.success(request, 'Configuración del motor de IA guardada.')
                return redirect('motor_ia')
        # Con errores se muestra la elección enviada, no la guardada.
        principal = form.data.get('motor_principal')
        principal = principal if principal in PROVEEDORES else configuracion_actual().principal
        respaldo = bool(form.data.get('respaldo_automatico'))
    else:
        form = ConfiguracionIAForm()
        config = configuracion_actual()
        principal, respaldo = config.principal, config.respaldo_automatico
    alternativo = PROVEEDOR_OLLAMA if principal == PROVEEDOR_GEMINI else PROVEEDOR_GEMINI
    fila = _fila_configuracion()
    gemini_modelo = gestor.proveedor(PROVEEDOR_GEMINI).modelo
    ollama_modelo = config_ollama()[1]
    return render(request, 'core/motor_ia.html', {
        'form': form,
        'principal': principal,
        'alternativo': alternativo,
        'principal_etiqueta': ETIQUETAS_MOTOR[principal],
        'alternativo_etiqueta': ETIQUETAS_MOTOR[alternativo],
        'respaldo': respaldo,
        'gemini_modelo': gemini_modelo,
        'ollama_modelo': ollama_modelo,
        'estados': [
            (PROVEEDOR_GEMINI, 'Gemini', gemini_modelo, gestor.persiste_analisis_publicaciones(PROVEEDOR_GEMINI)),
            (PROVEEDOR_OLLAMA, 'Llama 3.1', ollama_modelo, gestor.persiste_analisis_publicaciones(PROVEEDOR_OLLAMA)),
        ],
        'principal_persiste': gestor.persiste_analisis_publicaciones(principal),
        'ultimo_respaldo_en': getattr(fila, 'ultimo_respaldo_en', None),
        'ultimo_respaldo_detalle': getattr(fila, 'ultimo_respaldo_detalle', ''),
    })


def _fila_configuracion():
    """Fila guardada o None (sin configuración todavía, o tabla aún sin migrar)."""
    try:
        with transaction.atomic():
            return ConfiguracionIA.objects.filter(pk=ConfiguracionIA.PK).first()
    except DatabaseError:
        return None


@login_required(login_url='login')
@require_POST
@never_cache
def probar_motor_ia(request, proveedor):
    """Comprueba un motor sin ejecutar un análisis real.

    `alcance=conexion` (predeterminado) consulta si el servicio responde; `alcance=generacion`
    pide una respuesta mínima fija para comprobar que realmente puede generar. Ninguno guarda datos.
    """
    _exigir_administrador(request)
    if proveedor not in PROVEEDORES:
        raise Http404
    alcance = request.POST.get('alcance', 'conexion')
    if alcance not in ('conexion', 'generacion'):
        return JsonResponse({'error': 'alcance_invalido'}, status=400)
    motor = GestorIA().proveedor(proveedor)
    estado = motor.probar_generacion() if alcance == 'generacion' else motor.probar_conexion()
    return JsonResponse({
        'alcance': alcance,
        'proveedor': estado.proveedor,
        'estado': estado.estado,
        'etiqueta': estado.etiqueta,
        'detalle': estado.detalle,
        'modelo': estado.modelo,
    })
