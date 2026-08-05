"""Add report_windows (per-report start/end time window) to EmailReportConfig.

Replaces the older data_range_days / report_ranges / irrigation_hours fields
(those are kept on the model for back-compat but no longer read by the dispatch
logic). report_windows is a {report_type: {days_start,[hour_start],days_end,
[hour_end]}} map; each date-windowed report a config selects MUST have an entry.

Pure AddField (default=dict); no data migration — old configs simply have an
empty dict and get re-saved by the admin with explicit windows (now required).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0113_emailconfig_irrigation_hours'),
    ]

    operations = [
        migrations.AddField(
            model_name='emailreportconfig',
            name='report_windows',
            field=models.JSONField(
                blank=True, default=dict,
                help_text='{"irrigation":{"days_start":2,"hour_start":8,"days_end":0,"hour_end":8},'
                          '"work_reports":{"days_start":3,"days_end":1}}',
                verbose_name='各报表时间窗口'),
        ),
    ]
