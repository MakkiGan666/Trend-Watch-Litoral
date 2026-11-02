from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0013_clicpublicacion')]

    operations = [
        migrations.AddField(
            model_name='comentario', name='estado',
            field=models.CharField(choices=[
                ('pendiente', 'Pendiente de revisión'),
                ('publicado', 'Publicado'),
                ('rechazado', 'Rechazado'),
            ], default='publicado', max_length=10),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='comentario', name='estado',
            field=models.CharField(choices=[
                ('pendiente', 'Pendiente de revisión'),
                ('publicado', 'Publicado'),
                ('rechazado', 'Rechazado'),
            ], default='pendiente', max_length=10),
        ),
    ]
