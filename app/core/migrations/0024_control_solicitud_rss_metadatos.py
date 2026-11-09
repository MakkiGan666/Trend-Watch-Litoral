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
                ('ultimo_intento', models.DateTimeField(blank=True, null=True)),
                ('retry_after_hasta', models.DateTimeField(blank=True, null=True)),
                ('actualizado', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'core_control_solicitud_rss_metadatos',
            },
        ),
    ]
