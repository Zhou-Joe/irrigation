"""PM dispatch engine — generates GeneratedWorkOrders for due MaintenancePlans.

Runs daily via cron. For each active MaintenancePlan, computes the next due
date using ``dateutil.rrule``, and if the plan is within its ``lead_days``
window, generates a GeneratedWorkOrder record (preventing duplicates).

Dispatch creates ONLY a GWO (no WorkReport shell). The GWO carries the worker,
zones and remark so the PM tab can render and a worker can later complete the
task — at which point a new is_pm=True WorkReport is created and linked. This
keeps PM work out of 维修日志 and the normal WorkReport id sequence gap-free.

Usage:
    python manage.py generate_pm_workorders              # run for today
    python manage.py generate_pm_workorders --dry-run    # preview only
    python manage.py generate_pm_workorders --date 2026-07-15   # run for a specific date
"""

from datetime import date, timedelta
import logging

from dateutil.rrule import rrule, DAILY, WEEKLY, MONTHLY

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import (
    MaintenancePlan, GeneratedWorkOrder, Crew,
)

logger = logging.getLogger(__name__)


FREQ_MAP = {
    'days': DAILY,
    'weeks': WEEKLY,
    'months': MONTHLY,
}


class Command(BaseCommand):
    help = 'Generate WorkReports for due PM plans (daily cron dispatch engine).'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Preview without creating.')
        parser.add_argument('--date', type=str, default='', help='Run for a specific date (YYYY-MM-DD).')

    def handle(self, *args, **options):
        today = timezone.localdate()
        if options['date']:
            today = date.fromisoformat(options['date'])
        dry = options['dry_run']

        plans = MaintenancePlan.objects.filter(active=True).select_related('job_plan', 'crew')
        self.stdout.write(f'PM dispatch for {today} ({len(plans)} active plans, '
                          f'{"DRY RUN" if dry else "LIVE"})')

        generated = 0
        skipped_dup = 0
        skipped_not_due = 0
        skipped_no_zones = 0

        for plan in plans:
          try:
            # Guard: unknown frequency_unit would silently degrade to DAILY and
            # massively over-generate. Skip with a warning instead.
            if plan.frequency_unit not in FREQ_MAP:
                self.stdout.write(self.style.WARNING(
                    f'  {plan.pm_number}: unknown frequency_unit '
                    f'"{plan.frequency_unit}", skipping.'))
                skipped_not_due += 1
                continue

            # Backfill-capable dispatch: find ALL due occurrences in the window
            # (not just the next one). This catches missed cycles when cron was
            # down — each past occurrence that has no GWO yet gets generated.
            # The window extends from start_date through today + lead_days so we
            # catch both overdue backfill and upcoming lead-time dispatch.
            due_dates = self._due_dates_in_window(plan, today)
            if not due_dates:
                skipped_not_due += 1
                continue

            # Pre-fetch existing scheduled_dates to dedup (avoids N queries).
            existing_dates = set(
                GeneratedWorkOrder.objects
                .filter(plan=plan, scheduled_date__in=due_dates)
                .values_list('scheduled_date', flat=True)
            )
            new_dates = [d for d in due_dates if d not in existing_dates]
            if not new_dates:
                skipped_dup += 1
                continue

            # Resolve zones.
            zones = self._resolve_zones(plan)
            # Backfill crew on existing GWOs whose plan was crew-assigned after
            # they were created (common after bulk assign_pm_crews runs).
            if plan.crew_id:
                GeneratedWorkOrder.objects.filter(
                    plan=plan, crew__isnull=True
                ).update(crew=plan.crew)
            if not zones:
                self.stdout.write(self.style.WARNING(
                    f'  {plan.pm_number}: no zones linked, skipping.'))
                skipped_no_zones += 1
                continue

            # Resolve worker (crew leader or system fallback).
            worker = self._resolve_worker(plan, zones)
            if worker is None:
                self.stdout.write(self.style.WARNING(
                    f'  {plan.pm_number}: no active worker to assign, skipping.'))
                skipped_no_zones += 1
                continue

            for due_date in new_dates:
                if dry:
                    self.stdout.write(f'  [DRY] {plan.pm_number} → {due_date} '
                                      f'({len(zones)} zones, worker={worker})')
                    generated += 1
                    continue

                with transaction.atomic():
                    remark = plan.remark_template or f'{plan.job_plan.name} - {plan.pm_number}'
                    # Dispatch creates ONLY a GWO — no WorkReport shell. The GWO
                    # carries the dispatch payload (worker/zones/remark) so the PM
                    # tab can render and the completion form can seed a new
                    # is_pm=True WorkReport later. This keeps the normal WorkReport
                    # id sequence gap-free and PM work out of 维修日志.
                    gwo = GeneratedWorkOrder.objects.create(
                        plan=plan, crew=plan.crew, worker=worker,
                        scheduled_date=due_date, status='dispatched', remark=remark,
                    )
                    gwo.zones.set(zones)
                    plan.last_generated_date = today
                    plan.save(update_fields=['last_generated_date'])

                generated += 1
                self.stdout.write(self.style.SUCCESS(
                    f'  {plan.pm_number} → GWO #{gwo.id} (PM-{gwo.id}, {due_date}, '
                    f'{len(zones)} zones)'))

          except Exception as ex:
            # Isolate failures: one bad plan must not abort the whole dispatch.
            logger.exception('PM dispatch error for %s', plan.pm_number)
            self.stdout.write(self.style.ERROR(
                f'  {plan.pm_number}: ERROR — {ex}'))

        summary = (f'{generated} generated, {skipped_dup} already done, '
                   f'{skipped_not_due} not due, {skipped_no_zones} no zones.')
        if generated:
            logger.info('PM dispatch for %s: %s', today, summary)
        self.stdout.write(self.style.SUCCESS(f'\nDone: {summary}'))

    def _due_dates_in_window(self, plan, today):
        """Return ALL due dates that should be dispatched today (backfill-capable).

        Computes rrule occurrences from start_date through today + lead_days.
        Returns every occurrence whose due_date is >= today - lead_days. This
        means: a due date enters the window lead_days BEFORE it arrives (so
        the task appears early), and stays in the window FOREVER once passed
        (so a cron outage doesn't skip it — the missed occurrence is
        backfilled on the next run). The dedup check (no existing GWO for
        that plan+scheduled_date) prevents double-generation.

        Caller guards unknown frequency_unit before calling.
        """
        freq = FREQ_MAP[plan.frequency_unit]
        window_end = today + timedelta(days=max(plan.lead_days, 1))
        occurrences = list(rrule(freq, interval=plan.frequency_value,
                                 dtstart=plan.start_date, until=window_end))
        if not occurrences:
            return []
        # An occurrence is "due" once we're within lead_days of it (ahead or
        # behind). The lookback is unbounded (capped only by start_date) so
        # missed past occurrences are caught.
        threshold = today - timedelta(days=plan.lead_days)
        result = []
        for occ in occurrences:
            occ_date = occ.date() if hasattr(occ, 'date') else occ
            if occ_date >= threshold:
                result.append(occ_date)
        return result

    def _resolve_zones(self, plan):
        """Return the list/queryset of zones this plan targets."""
        level = plan.job_plan.asset_level
        if level == 'zone_group':
            return list(plan.zones.all())
        elif level == 'sat' and plan.satellite_id:
            return list(plan.satellite.zones.all())
        elif level == 'ccu' and plan.patch_id:
            return list(plan.patch.zones.all())
        # Fallback: if zones are directly linked, use them.
        if plan.zones.exists():
            return list(plan.zones.all())
        return []

    def _resolve_worker(self, plan, zones):
        """Resolve the worker to assign the generated WorkReport to.

        Priority: plan.crew.leader → crew member → Crew responsible for the
        zone's patch → system fallback (first active worker).
        """
        if plan.crew_id:
            crew = plan.crew
            if crew.leader_id:
                return crew.leader
            member = crew.members.first()
            if member:
                return member

        # Try to find a crew responsible for the first zone's Land.
        first_zone = zones[0] if zones else None
        if first_zone and first_zone.land_id:
            crew = Crew.objects.filter(lands=first_zone.land_id, active=True).first()
            if crew and crew.leader_id:
                return crew.leader

        # System fallback: first active worker.
        from core.models import Worker
        return Worker.objects.filter(active=True).first()
