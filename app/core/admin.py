from django.contrib import admin
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
    readonly_fields = ('hash_origen',)


@admin.register(Sentimiento)
class SentimientoAdmin(admin.ModelAdmin):
    list_display = ('id_publicacion_api', 'polaridad', 'confianza')
    list_filter = ('polaridad',)


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