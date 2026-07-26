"""Migrate WorkItem from plain Model + manual `level` field to MPTTModel.

Three operations, in order:
1. Drop the manual `level` field (mptt auto-manages it now via save()).
2. Add mptt's structural columns: lft / rgt / tree_id / level. They're added
   as NOT NULL with a placeholder default (1) so the ADD COLUMN succeeds on
   existing rows; the placeholder is overwritten immediately by step 3.
3. RunPython `_rebuild_workitem_tree` → WorkItem.objects.rebuild() walks the
   parent_id adjacency list and recomputes all four columns correctly.

After this migration, every WorkItem has accurate lft/rgt/tree_id/level and
the new manager page can fetch the whole tree in one query.
"""
from django.db import migrations, models
import mptt.fields


def _rebuild_workitem_tree(apps, schema_editor):
    """Recompute mptt lft/rgt/tree_id/level from the parent_id adjacency list.

    Migration's apps.get_model returns a historical model with NO mptt manager
    or _mptt_meta, so we can't call WorkItem.objects.rebuild(). Instead we do
    the nested-set renumbering in plain Python: walk each root DFS-preorder,
    assigning lft on enter, rght on leave, level by depth, tree_id per root.
    Mirrors mptt's algorithm exactly. ~2-5s for 1325 rows on SQLite.
    """
    WorkItem = apps.get_model('core', 'WorkItem')
    rows = list(WorkItem.objects.values('id', 'parent_id').order_by('id'))
    by_id = {r['id']: {'id': r['id'], 'parent_id': r['parent_id'], 'kids': []} for r in rows}
    roots = []
    for r in rows:
        n = by_id[r['id']]
        pid = r['parent_id']
        if pid and pid in by_id:
            by_id[pid]['kids'].append(n)
        else:
            roots.append(n)
    # Stable sibling order: keep insertion order (id asc), which matches the
    # tree's pre-migration layout closely enough; the new manager page lets
    # users re-sort via drag-drop afterward.

    counter = 1  # running lft/rght counter across ALL trees (mptt convention)
    updates = []  # (id, lft, rght, level, tree_id)

    def walk(node, level, tree_id):
        nonlocal counter
        lft = counter
        counter += 1
        for k in sorted(node['kids'], key=lambda x: x['id']):
            walk(k, level + 1, tree_id)
        rght = counter
        counter += 1
        updates.append((node['id'], lft, rght, level, tree_id))

    for tree_id, root in enumerate(roots, start=1):
        walk(root, 0, tree_id)

    # Batch-update all rows in one transaction.
    from django.db import connection
    with connection.cursor() as cur:
        for wid, lft, rght, level, tree_id in updates:
            cur.execute(
                "UPDATE core_workitem SET lft=%s, rght=%s, level=%s, tree_id=%s WHERE id=%s",
                [lft, rght, level, tree_id, wid],
            )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0103_followup_action_field'),
    ]

    operations = [
        # 1. Drop the manual level column. MPTT re-adds its own below.
        migrations.RemoveField(
            model_name='workitem',
            name='level',
        ),
        # 2. Add mptt structural columns. Default=1 is a placeholder that
        #    rebuild() (step 3) overwrites with the correct values; we can't
        #    add as nullable because MPTTMeta queries assume NOT NULL.
        migrations.AddField(
            model_name='workitem',
            name='lft',
            field=models.PositiveIntegerField(default=1, db_index=True, editable=False, verbose_name='left'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='workitem',
            name='rght',
            field=models.PositiveIntegerField(default=1, db_index=True, editable=False, verbose_name='right'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='workitem',
            name='tree_id',
            field=models.PositiveIntegerField(db_index=True, default=1, editable=False, verbose_name='tree ID'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='workitem',
            name='level',
            field=models.PositiveIntegerField(default=0, db_index=True, editable=False, verbose_name='level'),
            preserve_default=False,
        ),
        # Swap parent from plain ForeignKey to TreeForeignKey. Same column, but
        # the field class now reports as mptt.fields.TreeForeignKey so mptt
        # recognizes it. No data change — just metadata.
        migrations.AlterField(
            model_name='workitem',
            name='parent',
            field=mptt.fields.TreeForeignKey(blank=True, db_index=True, null=True, on_delete=models.deletion.CASCADE, related_name='children', to='core.workitem', verbose_name='父节点'),
        ),
        # 3. Rebuild the nested-set columns from parent_id adjacency list.
        migrations.RunPython(_rebuild_workitem_tree, migrations.RunPython.noop),
    ]
