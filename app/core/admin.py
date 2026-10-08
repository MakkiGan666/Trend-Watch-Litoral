from django.contrib import admin
from django import forms
from django.db import transaction
from django.core.exceptions import PermissionDenied
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


@admin.register(Publicacion)
class PublicacionAdmin(admin.ModelAdmin):
    list_display = ('id_publicacion_api', 'titulo', 'fuente', 'procesado_ia')
    list_filter = ('fuente', 'procesado_ia')
    search_fields = ('titulo', 'contenido', 'url')
    readonly_fields = ('hash_origen', 'procesado_ia')


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
class SentimientoAdmin(admin.ModelAdmin):
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
class LocacionAdmin(admin.ModelAdmin):
    list_display = ('id_publicacion_api', 'location', 'latitud', 'longitud')
    search_fields = ('location',)


@admin.register(RegistroDatos)
class RegistroDatosAdmin(admin.ModelAdmin):
    list_display = ('id_registro', 'fecha_ejecucion', 'estado')
    list_filter = ('estado',)


@admin.register(TemaTrend)
class TemaTrendAdmin(admin.ModelAdmin):
    search_fields = ('id_tema',)


@admin.register(PublicacionTema)
class PublicacionTemaAdmin(admin.ModelAdmin):
    list_display = ('id_publicacion_api',)


@admin.register(UserAuditoria)
class UserAuditoriaAdmin(admin.ModelAdmin):
    pass


@admin.register(VotoPublicacion)
class VotoPublicacionAdmin(admin.ModelAdmin):
    list_display = ('id_publicacion_api',)
