"""Migrate InventoryCategory from plain Model + manual `level` to MPTTModel.

Same shape as 0104_workitem_mptt (for WorkItem). Custom rebuild in pure Python
since apps.get_model in migrations returns a historical model without mptt's
tree manager. 389 rows, instant.
"""
from django.db import migrations, models
import mptt.fields


def _rebuild_inventory_tree(apps, schema_editor):
    """Recompute mptt lft/rght/tree_id/level from parent_id adjacency list.

    Mirrors mptt's nested-set renumbering: walk each root DFS-preorder,
    assigning lft on enter, rght on leave, level by depth, tree_id per root.
    Sibling order: by existing `order` then `code` (matches MPTTMeta).
    """
    InventoryCategory = apps.get_model('core', 'InventoryCategory')
    rows = list(InventoryCategory.objects.values('id', 'parent_id', 'order', 'code'))
    by_id = {r['id']: {'id': r['id'], 'parent_id': r['parent_id'],
                        'order': r['order'] or 0, 'code': r['code'] or '',
                        'kids': []} for r in rows}
    roots = []
    for r in rows:
        n = by_id[r['id']]
        pid = r['parent_id']
        if pid and pid in by_id:
            by_id[pid]['kids'].append(n)
        else:
            roots.append(n)
    # Sort roots + each node's kids by (order, code) for stable traversal.
    roots.sort(key=lambda x: (x['order'], x['code']))
    for n in by_id.values():
        n['kids'].sort(key=lambda x: (x['order'], x['code']))

    counter = 1
    updates = []

    def walk(node, level, tree_id):
        nonlocal counter
        lft = counter
        counter += 1
        for k in node['kids']:
            walk(k, level + 1, tree_id)
        rght = counter
        counter += 1
        updates.append((node['id'], lft, rght, level, tree_id))

    for tree_id, root in enumerate(roots, start=1):
        walk(root, 0, tree_id)

    from django.db import connection
    with connection.cursor() as cur:
        for wid, lft, rght, level, tree_id in updates:
            cur.execute(
                "UPDATE core_inventorycategory SET lft=%s, rght=%s, level=%s, tree_id=%s WHERE id=%s",
                [lft, rght, level, tree_id, wid],
            )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0104_workitem_mptt'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='inventorycategory',
            name='level',
        ),
        migrations.AddField(
            model_name='inventorycategory',
            name='lft',
            field=models.PositiveIntegerField(default=1, db_index=True, editable=False, verbose_name='left'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='inventorycategory',
            name='rght',
            field=models.PositiveIntegerField(default=1, db_index=True, editable=False, verbose_name='right'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='inventorycategory',
            name='tree_id',
            field=models.PositiveIntegerField(db_index=True, default=1, editable=False, verbose_name='tree ID'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='inventorycategory',
            name='level',
            field=models.PositiveIntegerField(default=0, db_index=True, editable=False, verbose_name='level'),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='inventorycategory',
            name='parent',
            field=mptt.fields.TreeForeignKey(blank=True, db_index=True, null=True, on_delete=models.deletion.CASCADE, related_name='children', to='core.inventorycategory', verbose_name='父节点'),
        ),
        migrations.RunPython(_rebuild_inventory_tree, migrations.RunPython.noop),
    ]
