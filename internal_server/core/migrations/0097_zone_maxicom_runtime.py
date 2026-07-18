"""Add Zone.maxicom_runtime — a JSON list of station Patch IDs that irrigate
the zone, derived from the zone code's A-B-C segments (CCU/satellite/channel).

Populated by the `populate_zone_maxicom_runtime` management command and
re-runnable after every nightly Maxicom import.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0096_pm_completion_and_extension'),
    ]

    operations = [
        migrations.AddField(
            model_name='zone',
            name='maxicom_runtime',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='Station Patch IDs that irrigate this zone '
                          '(derived from code A-B-C → CCU/satellite/channel).',
            ),
        ),
    ]
