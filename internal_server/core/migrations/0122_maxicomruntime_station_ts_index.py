# Composite index for the per-station latest-irrigation-day aggregation
# (_latest_runtime_by_station): MaxicomRuntime is the largest table (~390k
# rows) and previously only had per-timestamp indexes — the station+day
# grouping was a full scan per dashboard cache rebuild.
# MPTT drift ops stripped as usual (same as 0118/0119/0121).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0121_pipeline_valve_client_taxonomy'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='maxicomruntime',
            index=models.Index(fields=['station', 'timestamp'],
                               name='core_mr_station_ts'),
        ),
    ]
