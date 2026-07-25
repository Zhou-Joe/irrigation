"""Add parent_work_report + collab_status to WorkReport for the 疑难/待修 协作故事线 feature.

- parent_work_report: 自引用 FK，子工单(一线跟进) → 父工单(疑难/待修)。
- collab_status: 父工单聚合状态 ongoing/pending_review/resolved。

Data migration: existing open 疑难/待修 workorders (is_pending_repair=True OR
(is_difficult=True AND is_difficult_resolved=False)) get collab_status='ongoing'
so they enter the new collaborative flow.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0101_alter_workreportentry_unique_together_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='workreport',
            name='parent_work_report',
            field=models.ForeignKey(
                blank=True,
                help_text='一线提交的跟进子工单指向原疑难/待修工单；故事线协作',
                null=True,
                on_delete=models.deletion.CASCADE,
                related_name='followup_children',
                to='core.workreport',
                verbose_name='父工单(疑难/待修跟进)',
            ),
        ),
        migrations.AddField(
            model_name='workreport',
            name='collab_status',
            field=models.CharField(
                blank=True,
                default='',
                help_text='跟进中(ongoing)/待确认(pending_review)/已完成(resolved)；仅父工单有意义',
                max_length=20,
                verbose_name='协作状态',
            ),
        ),
        migrations.RunSQL(
            # Backfill existing open 疑难/待修 workorders into the new flow.
            sql=(
                "UPDATE core_workreport SET collab_status='ongoing' "
                "WHERE is_pending_repair=1 "
                "   OR (is_difficult=1 AND is_difficult_resolved=0);"
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
