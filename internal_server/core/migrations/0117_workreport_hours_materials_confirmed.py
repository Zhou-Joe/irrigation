"""Split project_confirmed into hours_confirmed + materials_confirmed.

The old single gate (project_confirmed) confirmed hours AND materials together.
This migration adds two independent booleans so a manager can confirm hours and
materials separately, then copies the old True value into both new fields so
already-confirmed orders keep counting toward their projects as before.
"""
from django.db import migrations, models


def copy_project_confirmed(apps, schema_editor):
    WorkReport = apps.get_model('core', 'WorkReport')
    WorkReport.objects.filter(project_confirmed=True).update(
        hours_confirmed=True, materials_confirmed=True)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0116_workreport_removed_project'),
    ]

    operations = [
        migrations.AddField(
            model_name='workreport',
            name='hours_confirmed',
            field=models.BooleanField(
                db_index=True, default=False, verbose_name='工时关联已确认'),
        ),
        migrations.AddField(
            model_name='workreport',
            name='materials_confirmed',
            field=models.BooleanField(
                db_index=True, default=False, verbose_name='物料关联已确认'),
        ),
        # Mark the old single-gate field as deprecated in its verbose_name so the
        # admin/inspector signals it has been superseded by the two fields above.
        migrations.AlterField(
            model_name='workreport',
            name='project_confirmed',
            field=models.BooleanField(
                db_index=True, default=False,
                verbose_name='项目关联已确认(已弃用)'),
        ),
        migrations.RunPython(copy_project_confirmed, noop),
    ]
