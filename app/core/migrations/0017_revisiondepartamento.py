from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('core', '0016_clic_ultima_visita')]

    operations = [
        migrations.CreateModel(
            name='RevisionDepartamento',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('metodo', models.CharField(choices=[('reglas', 'Reglas locales'), ('ia', 'IA')], max_length=8)),
                ('estado', models.CharField(choices=[('asignado', 'Departamento asignado'), ('provincial', 'Misiones sin departamento claro'), ('fuera', 'Fuera de Misiones'), ('varios', 'Varios departamentos'), ('sin_evidencia', 'Sin evidencia suficiente')], max_length=16)),
                ('departamento', models.CharField(blank=True, default='', max_length=30)),
                ('lugar', models.CharField(blank=True, default='', max_length=80)),
                ('evidencia', models.CharField(blank=True, default='', max_length=240)),
                ('modelo', models.CharField(blank=True, default='', max_length=80)),
                ('historial', models.JSONField(blank=True, default=list)),
                ('fecha_revision', models.DateTimeField(auto_now=True)),
                ('publicacion', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='revision_departamento', to='core.publicacion')),
            ],
        ),
    ]
