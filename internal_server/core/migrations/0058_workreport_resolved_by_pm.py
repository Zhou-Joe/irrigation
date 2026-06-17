# Adds WorkReport.resolved_by_pm (self FK) and backfills it from the remark
# text "已由计划性维修工单 #N 处理" that _resolve_pending_repairs has been
# writing for every resolved 待修 workorder. Going forward the FK is set
# directly by _resolve_pending_repairs; this backfill covers history.

import re

from django.db import migrations, models

_PM_RE = re.compile(r'已由计划性维修工单 #(\d+) 处理')


def backfill_resolved_by_pm(apps, schema_editor):
    WorkReport = apps.get_model('core', 'WorkReport')
    qs = WorkReport.objects.exclude(remark='').exclude(remark__isnull=True)
    valid_ids = set(WorkReport.objects.values_list('id', flat=True))
    updates = 0
    for r in qs.iterator():
        m = _PM_RE.search(r.remark or '')
        if not m:
            continue
        pm_id = int(m.group(1))
        if pm_id in valid_ids and r.resolved_by_pm_id != pm_id:
            r.resolved_by_pm_id = pm_id
            r.save(update_fields=['resolved_by_pm'])
            updates += 1
    if updates:
        # Best-effort log; migrations don't print to stdout reliably.
        pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0057_workreport_is_pending_repair'),
    ]

    operations = [
        migrations.AddField(
            model_name='workreport',
            name='resolved_by_pm',
            field=models.ForeignKey(
                blank=True,
                help_text='计划性维修工单处理本待修后自动回填；用于工单管理页展示闭环关系',
                null=True,
                on_delete=models.SET_NULL,
                related_name='resolved_repairs',
                to='core.workreport',
                verbose_name='处理该待修的计划性维修工单',
            ),
        ),
        migrations.RunPython(backfill_resolved_by_pm, migrations.RunPython.noop),
    ]
