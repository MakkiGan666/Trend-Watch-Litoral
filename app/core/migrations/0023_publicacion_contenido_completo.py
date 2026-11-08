from django.db import migrations, models


class Migration(migrations.Migration):
    """Marca disponibilidad del cuerpo sin reescribir publicaciones históricas."""

    dependencies = [
        ('core', '0022_merge_multifuente_sentimiento'),
    ]

    operations = [
        migrations.AddField(
            model_name='publicacion',
            name='contenido_completo',
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name='publicacion',
            name='contenido',
            field=models.TextField(blank=True),
        ),
        migrations.AddConstraint(
            model_name='publicacion',
            constraint=models.CheckConstraint(
                condition=models.Q(contenido_completo=True) | models.Q(contenido=''),
                name='publicacion_sin_cuerpo_vacio',
            ),
        ),
    ]
