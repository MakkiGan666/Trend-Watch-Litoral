from django.db import migrations


class Migration(migrations.Migration):
    """Une las dos ramas que partieron de 0010 (buscador y sentimiento de comentarios).

    No tiene operaciones: 0011_publicacion_texto_busqueda y 0011_sentimientocomentario
    tocan tablas distintas y pueden aplicarse en cualquier orden.
    """

    dependencies = [
        ('core', '0011_publicacion_texto_busqueda'),
        ('core', '0011_sentimientocomentario'),
    ]

    operations = []
