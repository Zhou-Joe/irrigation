"""Make WorkReport.location physically nullable.

The model declared ``location = ForeignKey(Patch, null=True, blank=True, ...)``
back in 0061, but the live SQLite column still carried a NOT NULL constraint
(schema drift — the column predated the AlterField, so the new nullable state
was recorded in the migration graph but the physical NOT NULL was never dropped
on this database). That made it impossible to create a workorder for any zone
whose land has no Patch — e.g. 酒店3 / 酒店4, zones with a Land but no patch_id
and no boundary. The INSERT raised
``NOT NULL constraint failed: core_workreport.location_id``.

A plain ``AlterField`` is a no-op here because Django compares field states and
sees "already nullable", emitting no SQL. To force the actual table rebuild that
SQLite requires to relax a column constraint, we drive the schema editor
directly with an explicit old→new field pair (NOT NULL → nullable). On SQLite
this rebuilds the table, recreates CHECK constraints and indexes, and copies
every row — exactly what a normal column change does, just guaranteed to run.
"""

from django.db import migrations, models


def force_location_nullable(apps, schema_editor):
    WorkReport = apps.get_model('core', 'WorkReport')
    Patch = apps.get_model('core', 'Patch')
    field = WorkReport._meta.get_field('location')

    # `field` already reflects the nullable model state. The DB still has NOT
    # NULL, so hand the schema editor an explicit NOT NULL "old" clone and the
    # nullable field as "new"; the mismatch forces a real table rebuild on
    # SQLite (and is a harmless no-op on backends already nullable).
    old_field = models.ForeignKey(
        blank=True,
        help_text=field.help_text,
        null=False,                       # the *physical* state we are moving away from
        on_delete=models.deletion.PROTECT,
        related_name='work_reports',
        to=Patch,
        verbose_name=field.verbose_name,
        db_column='location_id',
    )
    old_field.set_attributes_from_name('location')
    schema_editor.alter_field(WorkReport, old_field, field)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0062_patch_controller_number'),
    ]

    operations = [
        migrations.AlterField(
            model_name='workreport',
            name='location',
            field=models.ForeignKey(
                blank=True,
                help_text='可选；留空时按所选区域的所属位置自动填充',
                null=True,
                on_delete=models.deletion.PROTECT,
                related_name='work_reports',
                to='core.patch',
                verbose_name='位置/CCU',
            ),
        ),
        migrations.RunPython(force_location_nullable, noop),
    ]
