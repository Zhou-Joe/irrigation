# Generated for: move 待修 from a per-equipment toggle leaf to a top-level
# report-level boolean (placed before 疑难 in the workorder submittal form).

from django.db import migrations, models


def deactivate_daixiu_workitems_and_backfill_reports(apps, schema_editor):
    """Three coordinated data changes:

    1. Deactivate every WorkItem leaf named 待修 so it no longer renders in the
       work-content tree. We deactivate (active=False) rather than delete so
       historical WorkReportEntry FKs stay intact.
    2. Backfill the new is_pending_repair flag onto any existing report that
       still carries a 待修 entry, so the historical PM backlog survives.
    """
    WorkItem = apps.get_model('core', 'WorkItem')
    WorkReportEntry = apps.get_model('core', 'WorkReportEntry')
    WorkReport = apps.get_model('core', 'WorkReport')

    # 1. Hide 待修 template leaves from the picker.
    WorkItem.objects.filter(name_zh='待修', active=True).update(active=False)

    # 2. Backfill reports whose historical 待修 entries should still count.
    daixiu_item_ids = WorkItem.objects.filter(name_zh='待修').values_list('id', flat=True)
    pending_report_ids = set(
        WorkReportEntry.objects
        .filter(work_item_id__in=daixiu_item_ids, status='待修')
        .values_list('work_report_id', flat=True)
    )
    if pending_report_ids:
        WorkReport.objects.filter(id__in=pending_report_ids).update(is_pending_repair=True)


def reactivate_daixiu_workitems(apps, schema_editor):
    """Reverse: restore 待修 WorkItem leaves. is_pending_repair values are not
    cleared (the field is dropped on reverse anyway)."""
    WorkItem = apps.get_model('core', 'WorkItem')
    WorkItem.objects.filter(name_zh='待修', active=False).update(active=True)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0056_land_zone_land'),
    ]

    operations = [
        migrations.AddField(
            model_name='workreport',
            name='is_pending_repair',
            field=models.BooleanField(default=False, verbose_name='待修'),
        ),
        migrations.RunPython(
            deactivate_daixiu_workitems_and_backfill_reports,
            reactivate_daixiu_workitems,
        ),
    ]
