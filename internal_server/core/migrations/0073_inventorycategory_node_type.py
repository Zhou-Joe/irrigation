"""Add node_type to InventoryCategory so an empty directory isn't mistaken for a
stockable part. Backfill: any node that currently has children → 'category';
the rest → 'part' (preserves the pre-existing children-based rendering)."""
from django.db import migrations, models


def backfill_node_type(apps, schema_editor):
    InventoryCategory = apps.get_model('core', 'InventoryCategory')
    # Any node referenced as a parent by at least one child is a directory.
    child_parent_ids = set(
        InventoryCategory.objects.exclude(parent_id=None).values_list('parent_id', flat=True)
    )
    for cat in InventoryCategory.objects.all():
        cat.node_type = 'category' if cat.id in child_parent_ids else 'part'
        cat.save(update_fields=['node_type'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0072_inventorytransaction_work_report'),
    ]

    operations = [
        migrations.AddField(
            model_name='inventorycategory',
            name='node_type',
            field=models.CharField(
                choices=[('category', '目录'), ('part', '部件')],
                default='part',
                help_text='目录=可含子项的分类；部件=可出入库的具体物料',
                max_length=10,
                verbose_name='节点类型',
            ),
        ),
        migrations.RunPython(backfill_node_type, migrations.RunPython.noop),
    ]
