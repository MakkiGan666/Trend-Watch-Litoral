from django.db import migrations


class Migration(migrations.Migration):
    """Une la categoría del análisis de comentarios con la cadena 0011-0018 de main.

    Sin operaciones: 0012_sentimientocomentario_categoria conserva su nombre porque
    ya está aplicada en bases existentes; renombrarla obligaría a recrear la columna.
    """

    dependencies = [
        ('core', '0012_sentimientocomentario_categoria'),
        ('core', '0018_trend_clave'),
    ]

    operations = []
