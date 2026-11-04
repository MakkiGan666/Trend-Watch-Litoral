from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from .models import Publicacion
from .services.etiquetas import sincronizar_etiquetas


@receiver(pre_save, sender=Publicacion, dispatch_uid='core.publicacion.etiquetas.antes')
def recordar_texto(sender, instance, raw, using, update_fields, **kwargs):
    instance._texto_anterior_etiquetas = None
    if raw or (update_fields is not None and not {'titulo', 'contenido'} & set(update_fields)):
        return
    # Publicacion.save mantiene la transacción durante la escritura y la señal final.
    # Bloquear antes del UPDATE permite comparar con el texto realmente reemplazado.
    if instance.pk is not None:
        instance._texto_anterior_etiquetas = (
            sender.objects.using(using).select_for_update().filter(pk=instance.pk)
            .values('titulo', 'contenido').first()
        )


@receiver(post_save, sender=Publicacion, dispatch_uid='core.publicacion.etiquetas')
def actualizar_etiquetas(sender, instance, created, raw, using, update_fields, **kwargs):
    anterior = instance.__dict__.pop('_texto_anterior_etiquetas', None)
    if raw or (update_fields is not None and not {'titulo', 'contenido'} & set(update_fields)):
        return
    actual = sender.objects.using(using).filter(pk=instance.pk).values('titulo', 'contenido').get()
    if created or actual != anterior:
        sincronizar_etiquetas(instance, using=using)
