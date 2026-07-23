"""Reset past-due MaintenancePlans: roll start_date forward and clear stale GWOs.

Problem: a plan whose ``start_date`` is in the past keeps anchoring rrule
occurrences to an old date. On dispatch the engine either backfills a pile
of historical work orders or (with short lead_days) silently stays "not due".
Once a plan is stale, the cleanest recovery is to re-anchor its
``start_date`` to the *next future occurrence* and start the cycle fresh.

This command, for each active plan with ``start_date < today``:
  1. Computes the next rrule occurrence on/after today (the new anchor).
  2. Deletes that plan's uncompleted GeneratedWorkOrders
     (status in pending/dispatched/overdue). completed/skipped orders are kept
     as a historical record.
  3. Sets ``start_date`` to the new anchor.

After running, ``generate_pm_workorders`` will produce future work orders
anchored at the fresh date, with no stale backfill.

Safety: dry-run by default. Idempotent — re-running finds nothing to do once
start_dates are in the future.

Usage:
    python manage.py reset_pm_overdue              # dry-run (preview)
    python manage.py reset_pm_overdue --apply      # write changes
"""

from datetime import timedelta

from dateutil.rrule import rrule, DAILY, WEEKLY, MONTHLY

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import MaintenancePlan, GeneratedWorkOrder

FREQ = {'days': DAILY, 'weeks': WEEKLY, 'months': MONTHLY}
# Uncompleted statuses — these GWOs are deleted on reset. completed/skipped
# are kept as history.
DELETABLE_STATUSES = ('pending', 'dispatched', 'overdue')


class Command(BaseCommand):
    help = ('Re-anchor past-due PM start_dates to the next future occurrence '
            'and delete their uncompleted work orders (dry-run by default).')

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='Write changes (default: dry-run preview).')

    def handle(self, *args, **opts):
        today = timezone.localdate()
        do_apply = opts['apply']

        plans = (MaintenancePlan.objects.filter(active=True, start_date__lt=today)
                 .select_related('job_plan'))
        self.stdout.write(f'Reset past-due PMs for {today} '
                          f'({len(plans)} active plans with start_date < today, '
                          f'{"APPLY" if do_apply else "DRY RUN"})')

        reset = 0          # start_date moved
        no_future = 0      # no future occurrence found (e.g. bad frequency)
        gwo_deleted = 0    # uncompleted GWOs removed
        skipped = 0        # already had start_date >= today (shouldn't happen pre-filter)

        for plan in plans:
            if plan.frequency_unit not in FREQ:
                self.stdout.write(self.style.WARNING(
                    f'  {plan.pm_number}: unknown frequency_unit '
                    f'"{plan.frequency_unit}", skipping.'))
                no_future += 1
                continue

            # Next rrule occurrence on/after today — the new anchor.
            occs = list(rrule(FREQ[plan.frequency_unit],
                              interval=plan.frequency_value,
                              dtstart=plan.start_date,
                              until=today + timedelta(days=730)))
            future = [o.date() for o in occs if o.date() >= today]
            if not future:
                self.stdout.write(self.style.WARNING(
                    f'  {plan.pm_number}: no future occurrence within 730d, skipping.'))
                no_future += 1
                continue
            new_start = future[0]

            if new_start == plan.start_date:
                skipped += 1
                continue

            # Count uncompleted GWOs that will be deleted.
            stale = GeneratedWorkOrder.objects.filter(
                plan=plan, status__in=DELETABLE_STATUSES)

            if do_apply:
                with transaction.atomic():
                    # Delete the uncompleted GWOs. Dispatch no longer creates a
                    # WorkReport shell, so uncompleted GWOs have none to clean up;
                    # the work_report FK (SET_NULL) just detaches if one existed.
                    # completed/skipped orders stay as history.
                    removed = stale.count()
                    stale.delete()
                    gwo_deleted += removed
                    MaintenancePlan.objects.filter(id=plan.id).update(start_date=new_start)
            else:
                gwo_deleted += stale.count()

            reset += 1
            self.stdout.write(
                f'  {plan.pm_number}: {plan.start_date} → {new_start} '
                f'({plan.frequency_value}{plan.frequency_unit}, '
                f'{stale.count()} GWO removed)')

        self.stdout.write(self.style.SUCCESS(
            f'\nDone: {reset} reset, {skipped} unchanged, {no_future} no future occ'
            + (f', {gwo_deleted} GWOs deleted' if do_apply else '')
            + (' [DRY RUN]' if not do_apply else '')))

        # After a real reset, chain level_pm_schedule so the freshly-anchored
        # start_dates are spread evenly within each frequency group (avoids all
        # same-frequency PMs coming due on the same day). The order matters:
        # leveling re-anchors off min(start_date), so it must run AFTER reset.
        # Always chained on --apply (even if reset found nothing) so the button
        # is a reliable "reset + level" one-shot. Skipped on dry-run to keep
        # the preview focused on the reset itself.
        if do_apply:
            from django.core.management import call_command
            self.stdout.write(self.style.NOTICE(
                '\n→ Chaining level_pm_schedule (spread due dates evenly)...'))
            call_command('level_pm_schedule', '--apply', stdout=self.stdout)
        elif not do_apply:
            self.stdout.write(self.style.WARNING(
                'Note: on --apply, level_pm_schedule runs automatically after '
                'reset to spread due dates. Preview it separately with '
                '`level_pm_schedule`.'))
