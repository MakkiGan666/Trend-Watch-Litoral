import django.db.models.deletion
from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0032_remove_grupoeditorial_grupo_editorial_activo_aprobado_and_more'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='publicacion',
            index=models.Index(fields=['fuente', 'fecha_publicacion'], name='pub_fuente_fecha_sombra_idx'),
        ),
        migrations.CreateModel(
            name='TrabajoDeteccionSombraEditorial',
            fields=[
                ('publicacion', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE, primary_key=True, related_name='trabajo_deteccion_sombra_editorial', serialize=False, to='core.publicacion',
                )),
                ('estado', models.CharField(choices=[('PENDIENTE', 'Pendiente'), ('COMPLETADO', 'Completado'), ('REVISION_MANUAL', 'Revisión manual')], default='PENDIENTE', max_length=16)),
                ('intentos', models.PositiveSmallIntegerField(default=0)),
                ('candidatos_registrados', models.PositiveIntegerField(default=0)),
                ('codigo_error', models.CharField(blank=True, default='', max_length=48)),
                ('creado', models.DateTimeField(default=timezone.now)),
                ('actualizado', models.DateTimeField(auto_now=True)),
                ('completado', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'db_table': 'core_trabajo_deteccion_sombra_editorial',
                'ordering': ['creado', 'publicacion_id'],
                'indexes': [models.Index(fields=['estado', 'creado'], name='trabajo_sombra_estado_idx')],
                'constraints': [models.CheckConstraint(condition=models.Q(('estado__in', ['PENDIENTE', 'COMPLETADO', 'REVISION_MANUAL'])), name='trabajo_sombra_estado_valido')],
            },
        ),
    ]
