"""Add data_range_days / weekday / month_day to EmailReportConfig.

Lets the admin customize the data window (send-day minus N days → yesterday)
and the trigger day (weekday 0-6 for weekly, day 1-28 for monthly) instead of
the hardcoded defaults (yesterday / last-week / last-month, Monday / 1st).
All three are nullable → existing configs keep their current behavior.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0109_emailsmtpsetting'),
    ]

    operations = [
        migrations.AddField(
            model_name='emailreportconfig',
            name='data_range_days',
            field=models.IntegerField(blank=True, help_text='留空用频率默认；填 N = 发送日往前 N 天到前 1 天', null=True, verbose_name='数据范围(天)'),
        ),
        migrations.AddField(
            model_name='emailreportconfig',
            name='weekday',
            field=models.IntegerField(blank=True, null=True, verbose_name='周几发送'),
        ),
        migrations.AddField(
            model_name='emailreportconfig',
            name='month_day',
            field=models.IntegerField(blank=True, null=True, verbose_name='每月几号发送'),
        ),
    ]
