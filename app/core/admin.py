from django.contrib import admin
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.models import Group
from .services.identidad import errores_identidad, serializar_identidad
from django.db import transaction
from django.core.exceptions import PermissionDenied
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
)


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
