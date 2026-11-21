from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0034_rss_metadata_only_worker'),
    ]

    operations = [
        migrations.AddField(
            model_name='cacherobotsmultifuente',
            name='version_frescura',
            field=models.CharField(blank=True, default='', max_length=32),
        ),
    ]
