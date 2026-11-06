from django.db import migrations


class Migration(migrations.Migration):
    """Une las ramas de sentimiento y persistencia multifuente."""

    dependencies = [
        ('core', '0020_merge_etiquetas_y_categoria_sentimiento'),
        ('core', '0021_procesamientoiamultifuente'),
    ]

    operations = []
