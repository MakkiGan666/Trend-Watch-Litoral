from django.db import migrations


class Migration(migrations.Migration):
    """Une la rama de etiquetas de publicaciones (main) con la de categoría en
    el sentimiento de comentarios. Sin operaciones: tocan tablas distintas."""

    dependencies = [
        ('core', '0019_etiquetas_publicacion'),
        ('core', '0019_merge_categoria_sentimiento_y_trend_clave'),
    ]

    operations = []
