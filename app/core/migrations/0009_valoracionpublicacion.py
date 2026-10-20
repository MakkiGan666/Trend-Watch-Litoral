from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0008_comentario'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ValoracionPublicacion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sentimiento', models.CharField(choices=[('positivo', 'Positivo'), ('neutral', 'Neutral'), ('negativo', 'Negativo')], max_length=8)),
                ('fecha_creacion', models.DateTimeField(auto_now_add=True)),
                ('fecha_actualizacion', models.DateTimeField(auto_now=True)),
                ('publicacion', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='valoraciones', to='core.publicacion')),
                ('usuario', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='valoraciones_noticias', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'constraints': [
                    models.UniqueConstraint(fields=('publicacion', 'usuario'), name='valoracion_unica_usuario_noticia'),
                    models.CheckConstraint(condition=models.Q(sentimiento__in=['positivo', 'neutral', 'negativo']), name='valoracion_sentimiento_valido'),
                ],
            },
        ),
    ]
