from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Publicacion
from .services.etiquetas import sincronizar_etiquetas


@receiver(post_save, sender=Publicacion, dispatch_uid='core.publicacion.etiquetas')
def actualizar_etiquetas(sender, instance, created, update_fields, **kwargs):
    if created or update_fields is None or {'titulo', 'contenido'} & set(update_fields):
        sincronizar_etiquetas(instance)
