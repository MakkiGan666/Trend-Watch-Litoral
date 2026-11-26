from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0036_procedencia_analitica')]

    operations = [
        migrations.CreateModel(
            name='AplicacionLoteEnriquecimientoLocal',
            fields=[
                ('sha256', models.CharField(max_length=64, primary_key=True, serialize=False)),
                ('huella_resultante', models.CharField(max_length=64)),
                ('aplicado_en', models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]
