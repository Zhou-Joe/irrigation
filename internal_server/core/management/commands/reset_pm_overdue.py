"""Clear only expired PM work. Keep history, current work and future schedules."""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import ExtensionRequest
from core.pm_utils import overdue_orders


class Command(BaseCommand):
    help = 'Skip overdue PM orders without deleting records or moving plan anchors.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Apply; default is a read-only preview.')

    def handle(self, *args, **opts):
        with transaction.atomic():
            orders = overdue_orders()
            ids = list(orders.select_for_update().values_list('id', flat=True))
            count = len(ids)
            if opts['apply']:
                count = orders.filter(pk__in=ids).update(status='skipped')
                ExtensionRequest.objects.filter(gwo_id__in=ids, status='pending').update(
                    status='rejected', reviewed_at=timezone.now(), review_note='清理逾期工单，延期申请自动关闭',
                )
        self.stdout.write(f'Done: {count} overdue orders {"skipped" if opts["apply"] else "would be skipped (DRY RUN)"}.')
