from django.contrib import admin
from django.contrib import messages
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import path, reverse
from .services.identidad import errores_identidad, serializar_identidad
from django.db import transaction
from .services.scraper import generar_hash
from .services.integridad_sentimiento import (
    ConflictoSentimiento, sentimiento_unico, validar_numero,
)
from .models import (
    Publicacion,
    Sentimiento,
    Locacion,
    RegistroDatos,
    TemaTrend,
    PublicacionTema,
    UserAuditoria,
    VotoPublicacion,
    Comentario,
    RevisionDepartamento,
    GrupoEditorial,
    MiembroGrupoEditorial,
    EventoRevisionEditorial,
)
from .forms_agrupacion_editorial import (
    AccionGrupoEditorialForm, ActivarGrupoEditorialForm, CrearGrupoEditorialForm,
    DecisionMiembroEditorialForm,
)
from .services import agrupacion_editorial as servicio_agrupacion_editorial


class PublicacionAdminForm(forms.ModelForm):
    class Meta:
        model = Publicacion
        fields = '__all__'

    def clean(self):
        data = super().clean()
        # El hash representa el origen: se genera sólo al crear, igual que la API.
        if self.instance.pk is None:
            base_hash = data.get('url') or data.get('titulo')
            if base_hash:
                hash_origen = generar_hash(base_hash)
                if Publicacion.objects.filter(hash_origen=hash_origen).exists():
                    raise forms.ValidationError('Ya existe una publicación con el mismo origen (URL o título).')
                self.instance.hash_origen = hash_origen
        return data


@admin.register(GrupoEditorial)
class GrupoEditorialAdmin(admin.ModelAdmin):
    list_display = ('id', 'representante', 'estado', 'creado', 'creado_por')
    list_filter = ('estado',)
    search_fields = ('representante__titulo', 'representante__fuente')
    change_list_template = 'admin/core/grupoeditorial/changelist.html'

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in GrupoEditorial._meta.fields)

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path('crear-revision/', self.admin_site.admin_view(self.crear_revision), name='core_grupoeditorial_crear'),
            path('<int:object_id>/revision/', self.admin_site.admin_view(self.revision), name='core_grupoeditorial_revision'),
            path('<int:object_id>/miembro/<int:miembro_id>/', self.admin_site.admin_view(self.decidir), name='core_grupoeditorial_decidir'),
            path('<int:object_id>/activar/', self.admin_site.admin_view(self.activar), name='core_grupoeditorial_activar'),
            path('<int:object_id>/revocar/', self.admin_site.admin_view(self.revocar), name='core_grupoeditorial_revocar'),
        ]
        return custom + urls

    def _require(self, request, permission):
        if not request.user.has_perm(f'core.{permission}'):
            raise PermissionDenied

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return any(request.user.has_perm(f'core.{p}') for p in (
            'revisar_candidatos_editoriales', 'aprobar_agrupacion_editorial', 'revocar_agrupacion_editorial',
        ))

    def has_module_permission(self, request):
        return self.has_view_permission(request)

    def get_actions(self, request):
        return {}

    def changelist_view(self, request, extra_context=None):
        if request.method == 'POST':
            raise PermissionDenied
        extra_context = dict(extra_context or {})
        extra_context['puede_crear_revision'] = request.user.has_perm('core.revisar_candidatos_editoriales')
        return super().changelist_view(request, extra_context)

    def crear_revision(self, request):
        self._require(request, 'revisar_candidatos_editoriales')
        form = CrearGrupoEditorialForm(request.POST or None)
        if request.method == 'POST' and form.is_valid():
            try:
                grupo = servicio_agrupacion_editorial.crear_grupo(
                    actor=request.user,
                    publicacion_ids=form.cleaned_data['publicacion_ids'],
                    representante_id=form.cleaned_data['representante_id'],
                    motivo=form.cleaned_data['motivo'],
                )
            except (ValidationError, PermissionDenied) as error:
                form.add_error(None, error)
            else:
                messages.success(request, 'Grupo creado en estado de revisión; ningún resultado fue ocultado.')
                return HttpResponseRedirect(reverse('admin:core_grupoeditorial_revision', args=[grupo.pk]))
        return render(request, 'admin/core/grupoeditorial/formulario.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta,
            'title': 'Crear grupo en revisión', 'form': form,
        })

    def revision(self, request, object_id):
        grupo = get_object_or_404(GrupoEditorial.objects.prefetch_related('miembros__publicacion'), pk=object_id)
        if not self.has_view_permission(request, grupo):
            raise PermissionDenied
        return render(request, 'admin/core/grupoeditorial/revision.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta, 'grupo': grupo,
            'miembros': grupo.miembros.select_related('publicacion', 'revisado_por').order_by('rol', 'publicacion_id'),
            'puede_revisar': request.user.has_perm('core.revisar_candidatos_editoriales'),
            'puede_aprobar': request.user.has_perm('core.aprobar_agrupacion_editorial'),
            'puede_revocar': request.user.has_perm('core.revocar_agrupacion_editorial'),
        })

    def decidir(self, request, object_id, miembro_id):
        self._require(request, 'revisar_candidatos_editoriales')
        miembro = get_object_or_404(MiembroGrupoEditorial, pk=miembro_id, grupo_id=object_id)
        form = DecisionMiembroEditorialForm(request.POST or None)
        if request.method == 'POST' and form.is_valid():
            try:
                servicio_agrupacion_editorial.decidir_miembro(
                    actor=request.user, miembro_id=miembro.pk,
                    decision=form.cleaned_data['decision'], motivo=form.cleaned_data['motivo'],
                )
            except (ValidationError, PermissionDenied) as error:
                form.add_error(None, error)
            else:
                messages.success(request, 'Decisión registrada en la auditoría.')
                return HttpResponseRedirect(reverse('admin:core_grupoeditorial_revision', args=[object_id]))
        return render(request, 'admin/core/grupoeditorial/formulario.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta,
            'title': f'Revisar publicación #{miembro.publicacion_id}', 'form': form,
        })

    def activar(self, request, object_id):
        self._require(request, 'aprobar_agrupacion_editorial')
        grupo = get_object_or_404(GrupoEditorial, pk=object_id)
        form = ActivarGrupoEditorialForm(grupo, request.POST or None)
        if request.method == 'POST' and form.is_valid():
            try:
                resultado = servicio_agrupacion_editorial.activar_grupo(
                    actor=request.user, grupo_id=object_id,
                    representante_id=form.cleaned_data['representante_id'],
                    motivo=form.cleaned_data['motivo'],
                )
            except (ValidationError, PermissionDenied) as error:
                form.add_error(None, error)
            else:
                if resultado['requiere_revision']:
                    messages.warning(request, 'La representante final cambió. Todas las decisiones individuales volvieron a pendiente; revíselas antes de activar.')
                else:
                    messages.success(request, 'Grupo activado; publicaciones originales preservadas.')
                return HttpResponseRedirect(reverse('admin:core_grupoeditorial_revision', args=[object_id]))
        return render(request, 'admin/core/grupoeditorial/formulario.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta,
            'title': 'Aprobar y activar grupo editorial', 'form': form,
        })

    def revocar(self, request, object_id):
        return self._accion(request, object_id, 'revocar_agrupacion_editorial',
                            AccionGrupoEditorialForm, servicio_agrupacion_editorial.revocar_grupo,
                            'Grupo revocado; publicaciones originales preservadas.')

    def _accion(self, request, object_id, permiso, form_class, operacion, mensaje):
        self._require(request, permiso)
        form = form_class(request.POST or None)
        if request.method == 'POST' and form.is_valid():
            try:
                operacion(actor=request.user, grupo_id=object_id, motivo=form.cleaned_data['motivo'])
            except (ValidationError, PermissionDenied) as error:
                form.add_error(None, error)
            else:
                messages.success(request, mensaje)
                return HttpResponseRedirect(reverse('admin:core_grupoeditorial_revision', args=[object_id]))
        return render(request, 'admin/core/grupoeditorial/formulario.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta,
            'title': 'Confirmar acción editorial', 'form': form,
        })


@admin.register(MiembroGrupoEditorial)
class MiembroGrupoEditorialAdmin(admin.ModelAdmin):
    list_display = ('grupo', 'publicacion', 'rol', 'decision', 'vigente', 'revisado_por')
    list_filter = ('decision', 'rol', 'vigente')
    search_fields = ('publicacion__titulo', 'publicacion__fuente')
    readonly_fields = tuple(field.name for field in MiembroGrupoEditorial._meta.fields)

    def has_view_permission(self, request, obj=None):
        return any(request.user.has_perm(f'core.{p}') for p in (
            'revisar_candidatos_editoriales', 'aprobar_agrupacion_editorial', 'revocar_agrupacion_editorial',
        ))

    def has_module_permission(self, request):
        return self.has_view_permission(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(EventoRevisionEditorial)
class EventoRevisionEditorialAdmin(admin.ModelAdmin):
    list_display = ('grupo', 'miembro', 'tipo', 'actor', 'creado')
    list_filter = ('tipo',)
    readonly_fields = tuple(field.name for field in EventoRevisionEditorial._meta.fields)

    def has_view_permission(self, request, obj=None):
        return any(request.user.has_perm(f'core.{p}') for p in (
            'revisar_candidatos_editoriales', 'aprobar_agrupacion_editorial', 'revocar_agrupacion_editorial',
        ))

    def has_module_permission(self, request):
        return self.has_view_permission(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Publicacion)
class PublicacionAdmin(admin.ModelAdmin):
    form = PublicacionAdminForm
    list_display = ('id_publicacion_api', 'titulo', 'fuente', 'procesado_ia')
    list_filter = ('fuente', 'procesado_ia')
    search_fields = ('titulo', 'contenido', 'url')
    readonly_fields = ('hash_origen', 'procesado_ia')


class PublicacionRelacionAdmin(admin.ModelAdmin):
    """Omitir derivados también cuando el changelist une la publicación."""
    def get_queryset(self, request):
        return super().get_queryset(request).defer(
            'id_publicacion_api__titulo_busqueda', 'id_publicacion_api__contenido_busqueda',
        )


class SentimientoAdminForm(forms.ModelForm):
    class Meta:
        model = Sentimiento
        fields = '__all__'

    def clean_confianza(self):
        if isinstance(self.data.get('confianza'), bool):
            raise forms.ValidationError('confianza debe ser numérica, no booleana.')
        try:
            return validar_numero(self.cleaned_data['confianza'], 'confianza', 0, 1)
        except ValueError as error:
            raise forms.ValidationError(str(error)) from error

    def clean_polaridad(self):
        if isinstance(self.data.get('polaridad'), bool):
            raise forms.ValidationError('polaridad debe ser numérica, no booleana.')
        try:
            return validar_numero(self.cleaned_data['polaridad'], 'polaridad', -1, 1)
        except ValueError as error:
            raise forms.ValidationError(str(error)) from error

    def clean(self):
        data = super().clean()
        publicacion = data.get('id_publicacion_api')
        publicacion_id = publicacion.pk if publicacion is not None else self.instance.id_publicacion_api_id
        if publicacion_id is None:
            return data
        # El changeform de Django Admin mantiene una transacción exterior durante
        # validación y guardado; el bloqueo se conserva hasta finalizar la solicitud.
        with transaction.atomic():
            publicacion = Publicacion.objects.select_for_update().get(pk=publicacion_id)
            try:
                existente = sentimiento_unico(publicacion)
            except ConflictoSentimiento as error:
                raise forms.ValidationError(str(error)) from error
            if existente is not None and existente.pk != self.instance.pk:
                raise forms.ValidationError('Esta publicación ya tiene un sentimiento.')
        return data


@admin.register(Sentimiento)
class SentimientoAdmin(PublicacionRelacionAdmin):
    form = SentimientoAdminForm
    list_display = ('id_publicacion_api', 'polaridad', 'confianza')
    list_filter = ('polaridad',)

    def has_delete_permission(self, request, obj=None):
        return False

    def get_actions(self, request):
        acciones = super().get_actions(request)
        acciones.pop('delete_selected', None)
        return acciones

    def changelist_view(self, request, extra_context=None):
        if request.method == 'POST' and request.POST.get('action') == 'delete_selected':
            raise PermissionDenied('La eliminación administrativa de sentimientos está deshabilitada.')
        return super().changelist_view(request, extra_context)

    def get_readonly_fields(self, request, obj=None):
        return ('id_publicacion_api',) if obj is not None else ()

    def save_model(self, request, obj, form, change):
        with transaction.atomic():
            publicacion = Publicacion.objects.select_for_update().get(pk=obj.id_publicacion_api_id)
            existente = sentimiento_unico(publicacion)
            if ((existente is not None and existente.pk != obj.pk)
                    or (change and existente is None)):
                raise ConflictoSentimiento('El sentimiento cambió durante la edición; requiere revisión.')
            obj.confianza = validar_numero(obj.confianza, 'confianza', 0, 1)
            obj.polaridad = validar_numero(obj.polaridad, 'polaridad', -1, 1)
            super().save_model(request, obj, form, change)


@admin.register(Locacion)
class LocacionAdmin(PublicacionRelacionAdmin):
    list_display = ('id_publicacion_api', 'location', 'latitud', 'longitud')
    search_fields = ('location',)


@admin.register(RevisionDepartamento)
class RevisionDepartamentoAdmin(admin.ModelAdmin):
    list_display = ('publicacion', 'metodo', 'estado', 'departamento', 'lugar', 'fecha_revision')
    list_filter = ('metodo', 'estado', 'departamento')
    search_fields = ('publicacion__titulo', 'lugar', 'evidencia')
    readonly_fields = ('publicacion', 'metodo', 'estado', 'departamento', 'lugar', 'evidencia', 'modelo', 'historial', 'fecha_revision')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RegistroDatos)
class RegistroDatosAdmin(admin.ModelAdmin):
    list_display = ('id_registro', 'fecha_ejecucion', 'estado')
    list_filter = ('estado',)

    # Publicacion.id_registro usa CASCADE: borrar un registro eliminaría su histórico.
    def has_delete_permission(self, request, obj=None):
        return False

    def get_actions(self, request):
        acciones = super().get_actions(request)
        acciones.pop('delete_selected', None)
        return acciones

    def changelist_view(self, request, extra_context=None):
        if request.method == 'POST' and request.POST.get('action') == 'delete_selected':
            raise PermissionDenied('La eliminación administrativa de registros de ingesta está deshabilitada.')
        return super().changelist_view(request, extra_context)


@admin.register(TemaTrend)
class TemaTrendAdmin(admin.ModelAdmin):
    list_display = ('id_temas', 'id_trends')
    search_fields = ('id_temas__descripcion', 'id_trends__relevancia', 'id_trends__intervalos_periodo')


@admin.register(PublicacionTema)
class PublicacionTemaAdmin(PublicacionRelacionAdmin):
    list_display = ('id_publicacion_api',)


@admin.register(UserAuditoria)
class UserAuditoriaAdmin(admin.ModelAdmin):
    pass


@admin.register(VotoPublicacion)
class VotoPublicacionAdmin(PublicacionRelacionAdmin):
    list_display = ('id_publicacion_api',)


@admin.register(Comentario)
class ComentarioAdmin(admin.ModelAdmin):
    list_display = ('id', 'publicacion', 'autor', 'estado', 'fecha_creacion')
    list_filter = ('estado', 'fecha_creacion')
    search_fields = ('texto', 'autor__username', 'publicacion__titulo')
    actions = ('aprobar', 'rechazar')

    def _moderar(self, request, queryset, estado):
        if not self.has_change_permission(request):
            raise PermissionDenied('No tenés permiso para moderar comentarios.')
        with transaction.atomic():
            # Orden estable para lotes superpuestos. Leer el estado después de
            # bloquear evita auditar transiciones ficticias entre moderadores.
            comentarios = queryset.select_related(None).select_for_update().order_by('pk')
            for comentario in comentarios:
                anterior = comentario.estado
                if anterior == estado:
                    continue
                Comentario.objects.filter(pk=comentario.pk).update(estado=estado)
                comentario.estado = estado
                self.log_change(
                    request, comentario,
                    f'Moderación de comentario: estado {anterior} → {estado}.',
                )

    @admin.action(description='Aprobar comentarios seleccionados', permissions=['change'])
    def aprobar(self, request, queryset):
        self._moderar(request, queryset, Comentario.Estado.PUBLICADO)

    @admin.action(description='Rechazar comentarios seleccionados', permissions=['change'])
    def rechazar(self, request, queryset):
        self._moderar(request, queryset, Comentario.Estado.RECHAZADO)


class IdentidadUsuarioMixin:
    def clean(self):
        data = super().clean()
        nuevos = {}
        for campo in ('username', 'email'):
            valor = data.get(campo)
            anterior = getattr(self.instance, campo, '') or ''
            if valor is not None and (not self.instance.pk or valor.casefold() != anterior.casefold()):
                nuevos[campo] = valor
        if nuevos:
            for campo, mensaje in errores_identidad(excluir_pk=self.instance.pk, **nuevos).items():
                self.add_error(campo, mensaje)
        return data


class UsuarioAltaForm(IdentidadUsuarioMixin, UserAdmin.add_form):
    pass


class UsuarioCambioForm(IdentidadUsuarioMixin, UserAdmin.form):
    pass


# Conservar campos, widgets, permisos, grupos y flujo de contraseña del UserAdmin.
Usuario = get_user_model()
if admin.site.is_registered(Usuario):
    admin.site.unregister(Usuario)


class EscrituraTecnicaMixin:
    """Usuarios y grupos son fronteras de privilegios, incluso con permisos antiguos."""
    def changelist_view(self, request, extra_context=None):
        if request.method == 'POST' and not self.has_change_permission(request):
            raise PermissionDenied
        return super().changelist_view(request, extra_context)

    def has_add_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser


admin.site.unregister(Group)


@admin.register(Group)
class GrupoAdmin(EscrituraTecnicaMixin, GroupAdmin):
    pass


@admin.register(Usuario)
class UsuarioAdmin(EscrituraTecnicaMixin, UserAdmin):
    add_form = UsuarioAltaForm
    form = UsuarioCambioForm

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        if request.method == 'POST':
            with serializar_identidad():
                return super().changeform_view(request, object_id, form_url, extra_context)
        return super().changeform_view(request, object_id, form_url, extra_context)


    def user_change_password(self, request, id, form_url=''):
        # El formulario de Django puede guardar User completo según su versión.
        # Coordinar antes de su lectura, sin cambiar el contrato de contraseña.
        if request.method == 'POST':
            with serializar_identidad():
                return super().user_change_password(request, id, form_url)
        return super().user_change_password(request, id, form_url)
