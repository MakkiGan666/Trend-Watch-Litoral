from django.db import migrations, models


def copiar_intervalo_a_frecuencia(apps, schema_editor):
    Programacion = apps.get_model('core', 'ProgramacionIngestaMultifuente')
    Programacion.objects.using(schema_editor.connection.alias).all().update(
        frecuencia_segundos=models.F('intervalo_segundos'),
    )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0027_automatizacion_ingesta_multifuente'),
    ]

    operations = [
        migrations.AddField(
            model_name='programacioningestamultifuente',
            name='frecuencia_segundos',
            field=models.PositiveIntegerField(default=3600),
        ),
        migrations.RunPython(copiar_intervalo_a_frecuencia, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='programacioningestamultifuente',
            constraint=models.CheckConstraint(
                condition=models.Q(frecuencia_segundos__gte=60),
                name='programacion_multifuente_frecuencia_minima',
            ),
        ),
    ]
