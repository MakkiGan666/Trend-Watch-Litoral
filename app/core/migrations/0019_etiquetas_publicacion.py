from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('core', '0018_trend_clave')]

    operations = [
        migrations.CreateModel(
            name='Etiqueta',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=100)),
                ('slug', models.SlugField(max_length=110, unique=True)),
            ],
        ),
        migrations.CreateModel(
            name='PublicacionEtiqueta',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('posicion', models.PositiveSmallIntegerField()),
                ('etiqueta', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='publicaciones', to='core.etiqueta')),
                ('publicacion', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='etiquetas', to='core.publicacion')),
            ],
            options={'ordering': ['posicion', 'pk']},
        ),
        migrations.AddConstraint(
            model_name='publicacionetiqueta',
            constraint=models.UniqueConstraint(fields=('publicacion', 'etiqueta'), name='etiqueta_unica_por_publicacion'),
        ),
        migrations.AddConstraint(
            model_name='publicacionetiqueta',
            constraint=models.UniqueConstraint(fields=('publicacion', 'posicion'), name='posicion_unica_por_publicacion'),
        ),
    ]
