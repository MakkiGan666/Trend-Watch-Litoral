from django.db import migrations, models
import core.models


class Migration(migrations.Migration):
    dependencies = [('core', '0006_publicacion_imagen_fecha_departamento')]

    operations = [
        migrations.AddField(
            model_name='publicacion',
            name='imagen_archivo',
            field=models.ImageField(blank=True, default='', upload_to=core.models.ruta_imagen_publicacion),
        ),
    ]
