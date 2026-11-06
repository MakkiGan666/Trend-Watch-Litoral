from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """Agrega la categoría del comentario al análisis automático.

    Aditiva: un FK nullable hacia core.Categoria (la misma tabla de las noticias).
    Los análisis existentes quedan con categoría null hasta reanalizarse.
    Reversible mediante `migrate core 0011`.
    """

    dependencies = [
        ('core', '0011_sentimientocomentario'),
    ]

    operations = [
        migrations.AddField(
            model_name='sentimientocomentario',
            name='categoria',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='sentimientos_comentarios', to='core.categoria',
            ),
        ),
    ]
