from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [('core', '0020_aliasurlpublicacion')]
    operations = [
        migrations.CreateModel(
            name='ProcesamientoIAMultifuente',
            fields=[
                ('publicacion', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True, related_name='procesamiento_ia_multifuente', serialize=False, to='core.publicacion')),
                ('estado', models.CharField(choices=[('PENDIENTE', 'Todavía no enviado'), ('EN_PROCESO', 'Intento adquirido'), ('COMPLETADO', 'Resultado guardado'), ('ERROR', 'Respuesta o persistencia fallida; requiere revisión'), ('INCIERTO', 'Envío de resultado desconocido; no reenviar')], default='PENDIENTE', max_length=10)),
                ('huella_texto', models.CharField(blank=True, default='', max_length=64)),
                ('token_intento', models.UUIDField(blank=True, null=True)),
                ('codigo_error', models.CharField(blank=True, default='', max_length=40)),
                ('creado', models.DateTimeField(default=django.utils.timezone.now)),
                ('iniciado', models.DateTimeField(blank=True, null=True)),
                ('enviado', models.DateTimeField(blank=True, null=True)),
                ('finalizado', models.DateTimeField(blank=True, null=True)),
            ],
        ),
    ]
