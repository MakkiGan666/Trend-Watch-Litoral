from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0025_rss_lotes_metadatos'),
    ]

    operations = [
        migrations.AddField(
            model_name='trabajoloterssmetadatos',
            name='origen',
            field=models.CharField(
                choices=[('RSS', 'RSS'), ('HISTORICO', 'Histórico')],
                default='RSS',
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name='trabajoloterssmetadatos',
            name='procedencia',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddConstraint(
            model_name='trabajoloterssmetadatos',
            constraint=models.CheckConstraint(
                condition=models.Q(origen__in=['RSS', 'HISTORICO']),
                name='trabajo_lote_origen_valido',
            ),
        ),
    ]
