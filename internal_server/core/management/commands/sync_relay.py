"""Deprecated: cloud-relay sync for the legacy WorkLog/WorkOrder models.

Those models were removed; the v2 workorder flow replaced them. This command is
kept as a no-op stub so existing schedules/cron entries referencing it don't
error out. It logs a deprecation notice and exits.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = '(Deprecated) Cloud-relay sync for legacy WorkLog/WorkOrder — removed.'

    def handle(self, *args, **opts):
        self.stdout.write(self.style.WARNING(
            'sync_relay is deprecated: the WorkLog/WorkOrder models it synced '
            'have been removed in favor of the v2 workorder flow. No action taken.'
        ))
