"""Add a parallel 待修 toggle leaf under each 'repair-status' parent.

Parents like 漏水 / 阀门箱盖子缺失 / 降低阀箱高度 currently only have 已修复 as a child
toggle. A worker who finds such an issue but it's NOT yet fixed needs a 待修 option
alongside 已修复 — selecting it marks the work as pending-repair (linked to the
report-level 待修 flag in the form). This command adds those 待修 toggles; idempotent.
"""

from django.core.management.base import BaseCommand
from core.models import WorkItem


REPAIR_STATUS_NAMES = {'已修复'}


class Command(BaseCommand):
    help = 'Add 待修 toggle leaves under parents that have 已修复 children.'

    def handle(self, *args, **opts):
        # Parents that have a 已修复 child toggle → they are 'repair-status' groups.
        parent_ids = set(
            WorkItem.objects.filter(active=True, value_type='toggle',
                                    name_zh__in=REPAIR_STATUS_NAMES)
            .exclude(parent=None)
            .values_list('parent_id', flat=True)
        )

        created = 0
        skipped = 0
        for pid in parent_ids:
            parent = WorkItem.objects.get(id=pid)
            # Skip if a 待修 child already exists.
            if parent.children.filter(active=True, name_zh='待修').exists():
                skipped += 1
                continue
            # Find the 已修复 sibling to mirror its order/code prefix.
            sib = parent.children.filter(active=True, name_zh='已修复').first()
            order = (sib.order + 1) if sib else 0
            level = (sib.level) if sib else (parent.level + 1)
            # Build a code: parent code + next index.
            sib_count = parent.children.count()
            code = (parent.code + ('.' if parent.code else '') + str(sib_count + 1)) if parent.code else None
            WorkItem.objects.create(
                name_zh='待修',
                section=parent.section,
                value_type='toggle',
                unit='',
                is_project_scoped=False,
                order=order,
                level=level,
                parent=parent,
                code=code,
                status_options=[],
            )
            created += 1
            self.stdout.write(f'  + 待修 under "{parent.name_zh}" (id={parent.id})')

        self.stdout.write(self.style.SUCCESS(
            f'Done. created={created} skipped(existing)={skipped}'
        ))
