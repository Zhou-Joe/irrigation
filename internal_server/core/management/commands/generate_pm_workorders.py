"""Daily PM dispatch with calendar cycles, atomic plans and saved outcomes."""

from datetime import date, timedelta
import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import MaintenancePlan, GeneratedWorkOrder, PMDispatchRun
from core.pm_rotation import initialize_rotation, ROTATION_FIELDS
from core.pm_utils import (completion_deadline, occurrence, cycle_index,
                           plan_zones, matching_crew, crew_worker, next_due)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Generate PM work orders for due plans (daily cron dispatch engine).'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Preview without modifying data.')
        parser.add_argument('--date', default='', help='Run for a specific date (YYYY-MM-DD).')

    def handle(self, *args, **options):
        try:
            today = date.fromisoformat(options['date']) if options['date'] else timezone.localdate()
        except ValueError:
            raise CommandError('Invalid date; use YYYY-MM-DD.')
        dry = options['dry_run']
        projected, rotation_changes = initialize_rotation(today, apply=not dry)
        rotation_by_id = {p.pk: p for p in projected}
        ids = list(MaintenancePlan.objects.filter(active=True, job_plan__active=True).values_list('id', flat=True))
        self.stdout.write(f'PM dispatch for {today} ({len(ids)} active plans, {"DRY RUN" if dry else "LIVE"})')
        self.stdout.write(f'Rotation: {len(rotation_changes)} plans {"would be initialized" if dry else "initialized"}.')
        summary = dict(generated=0, already_done=0, not_due=0, unassignable=0, failed=0)
        details = []
        for plan_id in ids:
            plan = None
            try:
                with transaction.atomic():
                    plan = (MaintenancePlan.objects.select_for_update()
                            .select_related('job_plan', 'crew__leader', 'satellite')
                            .get(pk=plan_id))
                    if not plan.active or not plan.job_plan.active:
                        continue
                    if dry and plan.pk in rotation_by_id:
                        for name in ROTATION_FIELDS:
                            setattr(plan, name, getattr(rotation_by_id[plan.pk], name))
                    result = self._dispatch_plan(plan, today, dry)
                details.append(result)
                summary['generated'] += result['generated']
                if result['outcome'] != 'generated':
                    summary[result['outcome']] += 1
            except Exception as ex:
                summary['failed'] += 1
                logger.exception('PM dispatch error for plan %s', plan_id)
                details.append({'plan_id': plan_id, 'pm_number': plan.pm_number if plan else str(plan_id),
                                'outcome': 'failed', 'reason': str(ex), 'generated': 0})
                self.stdout.write(self.style.ERROR(f'  {details[-1]["pm_number"]}: ERROR — {ex}'))
        if not dry:
            PMDispatchRun.objects.create(run_date=today, summary=summary, details=details)
        message = (f'{summary["generated"]} generated, {summary["already_done"]} already done, '
                   f'{summary["not_due"]} not due, {summary["unassignable"]} unassignable, '
                   f'{summary["failed"]} failed. (non-generated counts are plans)')
        self.stdout.write(f'\nDone: {message}')
        if summary['failed']:
            raise CommandError(f'PM dispatch partially failed: {message}')

    def _dispatch_plan(self, plan, today, dry):
        due_dates = self._due_dates_in_window(plan, today)
        result = {'plan_id': plan.id, 'pm_number': plan.pm_number, 'generated': 0,
                  'next_due': next_due(plan, today).isoformat()}
        if not due_dates:
            return {**result, 'outcome': 'not_due', 'reason': '尚未进入提前生成窗口'}
        existing = set(plan.generated_orders.filter(scheduled_date__lte=due_dates[-1])
                       .values_list('scheduled_date', flat=True))
        new_dates = [day for day in due_dates if day not in existing]
        zones = self._resolve_zones(plan)
        crew, reason = matching_crew(plan, zones)
        if crew and not dry:
            plan.generated_orders.filter(crew__isnull=True, status__in=['dispatched', 'overdue']).update(crew=crew)
        if not new_dates:
            return {**result, 'outcome': 'already_done', 'reason': '窗口内各期工单均已生成，含已完成或已跳过'}
        if not zones:
            reason = '未关联有效区域'
        elif crew:
            plan.crew = crew
            worker = self._resolve_worker(plan, zones)
            if worker is None:
                reason = '负责班组没有启用的组长或成员'
        if reason:
            self.stdout.write(self.style.WARNING(f'  {plan.pm_number}: {reason}'))
            return {**result, 'outcome': 'unassignable', 'reason': reason, 'missing_cycles': len(new_dates)}
        remark = plan.remark_template or f'{plan.job_plan.name} - {plan.pm_number}'
        for due_date in new_dates:
            if dry:
                self.stdout.write(f'  [DRY] {plan.pm_number} → {due_date} ({len(zones)} zones)')
                result['generated'] += 1
                continue
            deadline = completion_deadline(plan, due_date)
            gwo, created = GeneratedWorkOrder.objects.get_or_create(
                plan=plan, scheduled_date=due_date,
                defaults={'crew': crew, 'worker': worker, 'deadline': deadline, 'remark': remark,
                          'status': 'overdue' if deadline < today else 'dispatched'},
            )
            if created:
                gwo.zones.set(zones)
                result['generated'] += 1
                self.stdout.write(f'  {plan.pm_number} → PM-{gwo.id} ({due_date}, {len(zones)} zones)')
        if result['generated'] and not dry:
            plan.last_generated_date = today
            plan.save(update_fields=['last_generated_date', 'crew'])
        return {**result, 'outcome': 'generated' if result['generated'] else 'already_done',
                'reason': '生成工单' if result['generated'] else '并发派发已生成，无需重复创建'}

    def _due_dates_in_window(self, plan, today):
        end = today + timedelta(days=plan.lead_days)
        return [occurrence(plan, index) for index in range(cycle_index(plan, end) + 1)]

    def _resolve_zones(self, plan):
        return plan_zones(plan)

    def _resolve_worker(self, plan, zones):
        return crew_worker(plan.crew)
