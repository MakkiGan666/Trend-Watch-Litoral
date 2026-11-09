from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0023_publicacion_contenido_completo'),
    ]

    operations = [
        migrations.CreateModel(
            name='ControlSolicitudRSSMetadatos',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fuente_id', models.CharField(max_length=64, unique=True)),
                ('estado', models.CharField(choices=[('LIBRE', 'Libre'), ('EN_CURSO', 'Solicitud en curso'), ('ESPERA', 'Espera activa'), ('REVISION_MANUAL', 'Revisión manual requerida')], default='LIBRE', max_length=20)),
                ('ultimo_intento', models.DateTimeField(blank=True, null=True)),
                ('retry_after_hasta', models.DateTimeField(blank=True, null=True)),
                ('actualizado', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'core_control_solicitud_rss_metadatos',
            },
        ),
        migrations.AddConstraint(
            model_name='controlsolicitudrssmetadatos',
            constraint=models.CheckConstraint(
                condition=models.Q(estado__in=['LIBRE', 'EN_CURSO', 'ESPERA', 'REVISION_MANUAL']),
                name='control_rss_estado_valido',
            ),
        ),
        migrations.AddConstraint(
            model_name='controlsolicitudrssmetadatos',
            constraint=models.CheckConstraint(
                condition=(~models.Q(estado='ESPERA') | models.Q(retry_after_hasta__isnull=False)),
                name='control_rss_espera_con_fecha',
            ),
        ),
    ]
