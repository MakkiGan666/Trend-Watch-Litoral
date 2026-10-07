from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0004_remove_publicacion_fecha_publicacion_fecha_captura_and_more'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='publicacion',
            options={'permissions': [
                ('ejecutar_scraping', 'Puede ejecutar scraping'),
                ('procesar_ia', 'Puede ejecutar procesamiento IA'),
            ]},
        ),
    ]
