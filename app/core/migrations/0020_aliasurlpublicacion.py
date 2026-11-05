from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('core', '0019_etiquetas_publicacion')]

    operations = [
        migrations.CreateModel(
            name='AliasURLPublicacion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fuente', models.CharField(max_length=100)),
                ('url_normalizada', models.URLField(max_length=500)),
                ('publicacion', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='aliases_urls', to='core.publicacion')),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('fuente', 'url_normalizada'), name='alias_url_unico_por_fuente')],
            },
        ),
    ]
