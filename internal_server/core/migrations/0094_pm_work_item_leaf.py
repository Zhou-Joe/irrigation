"""Add a text-typed WorkItem leaf under 维保定期检查(1.2) to carry the PM
JobPlan name when a field worker opens an auto-dispatched work order.

The leaf is keyed by code='1.2.pm' so re-running is idempotent.
"""
from django.db import migrations


def add_pm_leaf(apps, schema_editor):
    WorkItem = apps.get_model('core', 'WorkItem')
    parent = WorkItem.objects.filter(code='1.2').first()
    if parent is None:
        # 维保定期检查 root missing — seed_work_items hasn't run; skip silently.
        return
    WorkItem.objects.get_or_create(
        code='1.2.pm',
        defaults={
            'parent': parent,
            'name_zh': 'PM作业计划',
            'name_en': 'PM Job Plan',
            'order': 999,                 # sort after the numeric children
            'level': parent.level + 1,
            'section': 'routine_maint',
            'value_type': 'text',
            'is_project_scoped': False,
            'active': True,
        },
    )


def remove_pm_leaf(apps, schema_editor):
    WorkItem = apps.get_model('core', 'WorkItem')
    WorkItem.objects.filter(code='1.2.pm').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0093_generatedworkorder_crew_and_completed'),
    ]

    operations = [
        migrations.RunPython(add_pm_leaf, remove_pm_leaf),
    ]
