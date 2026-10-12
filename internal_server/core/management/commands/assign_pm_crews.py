"""Assign a single crew that covers the complete PM asset scope."""
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import MaintenancePlan
from core.pm_utils import matching_crew, plan_zones


class Command(BaseCommand):
    help = 'Auto-assign PM crews by CCU or complete Land coverage; leave ambiguity for manual assignment.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        assigned = already = unmatched = 0
        ids = MaintenancePlan.objects.filter(active=True, job_plan__active=True).values_list('id', flat=True)
        for plan_id in list(ids):
            with transaction.atomic():
                plan = (MaintenancePlan.objects.select_for_update()
                        .select_related('job_plan', 'crew', 'satellite').get(pk=plan_id))
                if plan.crew_id:
                    already += 1
                    continue
                crew, reason = matching_crew(plan, plan_zones(plan))
                if not crew:
                    unmatched += 1
                    self.stdout.write(f'  {plan.pm_number}: {reason}')
                    continue
                assigned += 1
                if not opts['dry_run']:
                    plan.crew = crew
                    plan.save(update_fields=['crew'])
                    plan.generated_orders.filter(crew__isnull=True, status__in=['dispatched', 'overdue']).update(crew=crew)
                self.stdout.write(f'  {plan.pm_number} → {crew.name}')
        self.stdout.write(f'Done: {assigned} assigned, {already} already had crew, {unmatched} no matching crew.'
                          + (' [DRY RUN]' if opts['dry_run'] else ''))
