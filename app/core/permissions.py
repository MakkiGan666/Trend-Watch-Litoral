from rest_framework.permissions import BasePermission


class PermisosDjango(BasePermission):
    permisos = ()

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.has_perms(self.permisos)


class ProcesarIA(PermisosDjango):
    permisos = ('core.procesar_ia',)


class EjecutarIngesta(PermisosDjango):
    permisos = ('core.ejecutar_scraping', 'core.procesar_ia')


class CrearPublicacion(PermisosDjango):
    permisos = ('core.add_publicacion',)


class EditarPublicacion(PermisosDjango):
    permisos = ('core.change_publicacion',)


class EliminarPublicacion(PermisosDjango):
    permisos = ('core.delete_publicacion',)
