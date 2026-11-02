from django.db import migrations, models


def identificar_lecturas(apps, schema_editor):
    Trend = apps.get_model('core', 'Trend')
    TemaTrend = apps.get_model('core', 'TemaTrend')
    alias = schema_editor.connection.alias
    tendencias = Trend.objects.using(alias).filter(
        relevancia='Lecturas', intervalos_periodo='7 días',
    ).order_by('pk')
    canonica = tendencias.first()
    if canonica is None:
        return
    # El menor ID es una elección estable, sin borrar ni reescribir históricos.
    temas = TemaTrend.objects.using(alias).filter(
        id_trends_id__in=tendencias.values('pk'),
    ).values_list('id_temas_id', flat=True).distinct()
    for tema_id in list(temas):
        TemaTrend.objects.using(alias).get_or_create(id_temas_id=tema_id, id_trends_id=canonica.pk)
    Trend.objects.using(alias).filter(pk=canonica.pk).update(clave='lecturas_7_dias')


class Migration(migrations.Migration):
    dependencies = [('core', '0017_revisiondepartamento')]
    operations = [
        migrations.AddField(
            model_name='trend', name='clave',
            field=models.CharField(blank=True, editable=False, max_length=50, null=True, unique=True),
        ),
        migrations.RunPython(identificar_lecturas, migrations.RunPython.noop),
    ]
