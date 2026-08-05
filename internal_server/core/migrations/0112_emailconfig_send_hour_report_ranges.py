"""Add per-config send_hour and per-report-type data range to EmailReportConfig.

Both fields are nullable/defaulted, so this is a non-destructive add:
  - send_hour (null=True) → existing configs keep firing at the 07:00 cron run
    (null is treated as hour 7 in _is_due_now). Only meaningful once the
    production cron is changed from `0 7 * * *` to `0 * * * *` (hourly).
  - report_ranges (JSONField, default {}) → per-report-type N-days map for the
    day-windowed reports (work_reports / inventory_txn). Empty dict falls back
    to the legacy global data_range_days, then to the frequency default.

No RunPython: nothing to back-fill (null/empty defaults are the back-compat
values themselves).
"""
from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0111_emailconfig_multiselect_body_ccu'),
    ]

    operations = [
        migrations.AddField(
            model_name='emailreportconfig',
            name='send_hour',
            field=models.IntegerField(
                blank=True, help_text='0-23，留空=7点。需要 cron 改为每小时运行才生效',
                null=True, validators=[django.core.validators.MinValueValidator(0),
                                       django.core.validators.MaxValueValidator(23)],
                verbose_name='发送时间(小时)'),
        ),
        migrations.AddField(
            model_name='emailreportconfig',
            name='report_ranges',
            field=models.JSONField(
                blank=True, default=dict,
                help_text='{"work_reports": 3, "inventory_txn": 7}；缺省用 data_range_days 或频率默认',
                verbose_name='各报表数据范围'),
        ),
    ]
