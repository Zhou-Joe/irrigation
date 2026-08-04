"""Add multi-select report types, CCU subset, and editable subject/body to
EmailReportConfig.

Backward compatible:
  - report_types (JSON list) defaults to [] and is back-filled from the legacy
    single report_type in a RunPython step so existing configs keep firing the
    same report after the upgrade.
  - ccu_ids (JSON list) defaults to [] = all CCUs (no behaviour change).
  - email_subject / email_body default to '' = use the built-in default text.

report_type is retained (now blank=True) for backward-compat reads and as the
single-select mirror of report_types[0].
"""
from django.db import migrations, models


def backfill_report_types(apps, schema_editor):
    """Populate report_types from the legacy single report_type field."""
    EmailReportConfig = apps.get_model('core', 'EmailReportConfig')
    for cfg in EmailReportConfig.objects.all():
        if cfg.report_type and not cfg.report_types:
            cfg.report_types = [cfg.report_type]
            cfg.save(update_fields=['report_types'])


def reverse_backfill(apps, schema_editor):
    # No-op reverse: leaving report_types populated is harmless.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0110_emailconfig_daterange_weekday_monthday'),
    ]

    operations = [
        migrations.AddField(
            model_name='emailreportconfig',
            name='report_types',
            field=models.JSONField(
                blank=True, default=list, help_text='选中的每种报表各生成一个 Excel 附件，随同一封邮件发送',
                verbose_name='报表（多选）'),
        ),
        migrations.AddField(
            model_name='emailreportconfig',
            name='ccu_ids',
            field=models.JSONField(
                blank=True, default=list, help_text='留空=全部 CCU；填 CCU id 列表=仅导出这些 CCU（仅灌溉报表生效）',
                verbose_name='灌溉 CCU 范围'),
        ),
        migrations.AddField(
            model_name='emailreportconfig',
            name='email_subject',
            field=models.CharField(
                blank=True, help_text='留空用默认主题。可用 {name} {types} {period}',
                max_length=200, verbose_name='邮件主题'),
        ),
        migrations.AddField(
            model_name='emailreportconfig',
            name='email_body',
            field=models.TextField(
                blank=True, help_text='留空用默认正文。可用 {name} {types} {period}',
                verbose_name='邮件正文'),
        ),
        migrations.AlterField(
            model_name='emailreportconfig',
            name='report_type',
            field=models.CharField(
                blank=True, choices=[('work_reports', '维修工单记录'), ('irrigation', '灌溉运行报表'),
                                     ('projects', '项目管理'), ('inventory_catalog', '库存目录'),
                                     ('inventory_txn', '库存出入库流水'), ('purchase_orders', '采购订单'),
                                     ('zones', '区域/地块目录')],
                max_length=40, verbose_name='报表'),
        ),
        migrations.RunPython(backfill_report_types, reverse_backfill),
    ]
