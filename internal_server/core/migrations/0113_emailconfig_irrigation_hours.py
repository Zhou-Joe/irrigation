"""Add irrigation_hours (hour-precision data range) to EmailReportConfig.

The irrigation report needs hour granularity ("past N hours"), while
report_ranges only stores day counts. irrigation_hours is null=True → falls
back to report_ranges / data_range_days / 频率默认 (full-day 00:00-23:59).
"""
from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0112_emailconfig_send_hour_report_ranges'),
    ]

    operations = [
        migrations.AddField(
            model_name='emailreportconfig',
            name='irrigation_hours',
            field=models.IntegerField(
                blank=True, help_text='过去 N 小时（如 6 = 过去6小时）。仅灌溉报表；留空按天默认',
                null=True, validators=[django.core.validators.MinValueValidator(1),
                                       django.core.validators.MaxValueValidator(720)],
                verbose_name='灌溉数据范围(小时)'),
        ),
    ]
