"""Preview or explicitly rebalance the same rotation used by daily dispatch.

Ordinary dispatch initializes new plans and preserves existing phases. Use this
command after bulk changes when the whole active frequency group should be
rebalanced. Issued orders remain intact; changed phases start after their last
issued cycle. Dry runs never modify plans or orders.
"""

from collections import Counter
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import MaintenancePlan, GeneratedWorkOrder
from core.pm_rotation import initialize_rotation
from core.pm_utils import cycle_index, occurrence


def projected_load(plans, today, days):
    end = today + timedelta(days=days)
    planned = set()
    plan_ids = []
    for plan in plans:
        plan_ids.append(plan.pk)
        first = max(0, cycle_index(plan, today))
        for index in range(first, cycle_index(plan, end - timedelta(days=1)) + 1):
            day = occurrence(plan, index)
            if today <= day < end:
                planned.add((plan.pk, day))
    # Releveling preserves issued work, which can still cause peaks during
    # the transition. Include it so preview does not promise immediate flattening.
    planned.update(GeneratedWorkOrder.objects.filter(
        plan_id__in=plan_ids, scheduled_date__gte=today, scheduled_date__lt=end,
    ).values_list('plan_id', 'scheduled_date'))
    return Counter(day for _, day in planned)


class Command(BaseCommand):
    help = 'Rebalance active PM rotations (read-only preview unless --apply).'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Persist the projected rotation.')
        parser.add_argument('--exclude-units', nargs='*', default=[],
                            choices=['days', 'weeks', 'months'], help='Frequency units to skip.')
        parser.add_argument('--preview-days', type=int, default=90, help='Days of projected load.')
        parser.add_argument('--date', default='', help='Preview/apply as of YYYY-MM-DD.')

    def handle(self, *args, **opts):
        try:
            today = date.fromisoformat(opts['date']) if opts['date'] else timezone.localdate()
        except ValueError:
            raise CommandError('Invalid date; use YYYY-MM-DD.')
        days = opts['preview_days']
        if days < 1:
            raise CommandError('--preview-days must be positive.')
        before = list(MaintenancePlan.objects.filter(
            active=True, job_plan__active=True, frequency_value__gte=1,
            frequency_unit__in=['days', 'weeks', 'months'],
        ).exclude(frequency_unit__in=opts['exclude_units']))
        plans, changes = initialize_rotation(today, apply=opts['apply'], relevel=True,
                                             exclude_units=opts['exclude_units'])
        date_changes = [(plan, old) for plan, old in changes if plan.start_date != old]
        mode = 'APPLY' if opts['apply'] else 'DRY RUN'
        self.stdout.write(f'{mode}: {len(date_changes)} of {len(plans)} active plans rescheduled; '
                          f'{len(changes)} rotation settings updated.')
        for plan, old in date_changes:
            self.stdout.write(f'  {plan.pm_number}: {old} → {plan.start_date}')
        old_load = projected_load(before, today, days)
        new_load = projected_load(plans, today, days)
        self.stdout.write(f'\nScheduled load over {days} days (all occurrences):')
        self.stdout.write(f'  BEFORE peak: {max(old_load.values(), default=0)} orders/day')
        self.stdout.write(f'  AFTER peak:  {max(new_load.values(), default=0)} orders/day')
        for offset in range(0, days, 7):
            start = today + timedelta(days=offset)
            end = min(today + timedelta(days=days), start + timedelta(days=7))
            count = sum(count for day, count in new_load.items() if start <= day < end)
            self.stdout.write(f'  {start}: {count} orders')
        if not opts['apply']:
            self.stdout.write('Dry-run only; use --apply to save. Issued work orders are preserved.')
