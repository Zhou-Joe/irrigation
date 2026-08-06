"""Add project_confirmed to WorkReport.

New work orders with a project association start UNconfirmed (False) and must be
manager-confirmed before they count toward project labor/material stats. To
avoid retroactively hiding all historical project-linked work, existing reports
that already have a project-linked entry are back-filled to True (treated as
already confirmed). Reports with no project link keep the default False —
harmless since the field is only consulted when an entry points at a project.
"""
from django.db import migrations, models


def backfill_confirmed(apps, schema_editor):
    """Mark existing project-linked work orders as already confirmed."""
    WorkReport = apps.get_model('core', 'WorkReport')
    WorkReportEntry = apps.get_model('core', 'WorkReportEntry')
    # Reports that have at least one entry with a non-null project → confirmed.
    linked_ids = set(WorkReportEntry.objects.exclude(project=None)
                     .values_list('work_report_id', flat=True))
    if linked_ids:
        WorkReport.objects.filter(pk__in=linked_ids).update(project_confirmed=True)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0114_emailconfig_report_windows'),
    ]

    operations = [
        migrations.AddField(
            model_name='workreport',
            name='project_confirmed',
            field=models.BooleanField(
                db_index=True, default=False, verbose_name='项目关联已确认'),
        ),
        migrations.RunPython(backfill_confirmed, migrations.RunPython.noop),
    ]
