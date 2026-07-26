# Generated for heatmap zone exclusion feature.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0105_inventory_mptt'),
    ]

    operations = [
        migrations.AddField(
            model_name='zone',
            name='heatmap_excluded',
            field=models.BooleanField(
                default=False,
                help_text='经理手动排除：该区域在 /irrigation/ 热力图上不再显示',
                verbose_name='热力图已排除',
            ),
        ),
    ]
