from django.db import migrations, models
import core.busqueda_texto_v1


class Migration(migrations.Migration):
    dependencies = [('core', '0010_perfilusuario_publicacionguardada')]

    operations = [
        migrations.AddField(
            model_name='publicacion', name='titulo_busqueda',
            field=models.GeneratedField(
                expression=core.busqueda_texto_v1.TextoComparableV1('titulo'),
                output_field=models.TextField(), db_persist=True, serialize=False,
            ),
        ),
        migrations.AddField(
            model_name='publicacion', name='contenido_busqueda',
            field=models.GeneratedField(
                expression=core.busqueda_texto_v1.TextoComparableV1('contenido'),
                output_field=models.TextField(), db_persist=True, serialize=False,
            ),
        ),
    ]
