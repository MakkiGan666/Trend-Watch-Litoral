from django.db import migrations, models
import django.utils.timezone


def conservar_fecha_lectura(apps, schema_editor):
    ClicPublicacion = apps.get_model('core', 'ClicPublicacion')
    ClicPublicacion.objects.update(ultima_visita=models.F('fecha_creacion'))


class Migration(migrations.Migration):
    dependencies = [('core', '0015_revisar_comentarios_existentes')]

    operations = [
        migrations.AddField(
            model_name='clicpublicacion', name='ultima_visita',
            field=models.DateTimeField(null=True),
        ),
        migrations.RunPython(conservar_fecha_lectura, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='clicpublicacion', name='ultima_visita',
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
    ]
