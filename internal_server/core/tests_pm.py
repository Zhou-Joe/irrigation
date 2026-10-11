"""Regression tests for PM dispatch, cycle deadlines and bulk skip."""

from datetime import date, timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command, CommandError
from django.test import TestCase
from django.urls import reverse

from core.management.commands.generate_pm_workorders import Command
from core.models import (
    Crew, ExtensionRequest, GeneratedWorkOrder, JobPlanTemplate, Land,
    MaintenancePlan, Worker, WorkReport, Zone,
)
from core.notifications import pm_tasks_for_field_worker
from core.pm_utils import completion_deadline, is_overdue
from core.views import _pm_gwo_queryset, _serialize_pm_tasks


class PMFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = date(2026, 10, 12)
        cls.user = User.objects.create_user('pm-worker')
        cls.manager = User.objects.create_user('pm-manager', is_staff=True)
        cls.worker = Worker.objects.create(
            user=cls.user, employee_id='PM-W1', full_name='PM Worker')
        cls.crew = Crew.objects.create(name='PM Crew', leader=cls.worker)
        cls.job = JobPlanTemplate.objects.create(name='PM Regression', asset_level='zone_group')
        cls.zone = Zone.objects.create(code='PM-Z1', name='PM Zone')
        cls.plan = MaintenancePlan.objects.create(
            pm_number='PM-TEST', job_plan=cls.job, crew=cls.crew,
            frequency_value=1, frequency_unit='weeks', lead_days=0,
            start_date=cls.today,
        )
        cls.plan.zones.add(cls.zone)

    def order(self, days=0, status='dispatched', **kwargs):
        return GeneratedWorkOrder.objects.create(
            plan=self.plan, scheduled_date=self.today + timedelta(days=days),
            status=status, worker=self.worker, **kwargs)

    def dispatch(self, **kwargs):
        out = StringIO()
        call_command('generate_pm_workorders', date=self.today.isoformat(), stdout=out, **kwargs)
        return out.getvalue()

    def post(self, name, args=None):
        return self.client.post(reverse('core:' + name, args=args), HTTP_HOST='127.0.0.1')


class PMDispatchTests(PMFixture):
    def test_backfills_history_beyond_lead_days_and_marks_only_expired_cycles(self):
        self.plan.start_date = self.today - timedelta(weeks=3)
        self.plan.save()
        self.dispatch()
        self.assertEqual(list(self.plan.generated_orders.order_by('scheduled_date')
                              .values_list('scheduled_date', 'status')), [
            (self.today - timedelta(weeks=3), 'overdue'),
            (self.today - timedelta(weeks=2), 'overdue'),
            (self.today - timedelta(weeks=1), 'dispatched'),
            (self.today, 'dispatched'),
        ])
        self.assertEqual(WorkReport.objects.count(), 0)

    def test_zero_lead_time_does_not_generate_tomorrows_task(self):
        self.plan.start_date = self.today + timedelta(days=1)
        self.plan.save()
        self.dispatch()
        self.assertFalse(self.plan.generated_orders.exists())

    def test_lead_time_generates_early_without_shortening_cycle(self):
        self.plan.start_date = self.today + timedelta(days=28)
        self.plan.lead_days = 28
        self.plan.save()
        self.dispatch()
        gwo = self.plan.generated_orders.get()
        self.assertEqual(gwo.scheduled_date, self.today + timedelta(days=28))
        self.assertEqual(gwo.status, 'dispatched')
        self.assertEqual(completion_deadline(self.plan, gwo.scheduled_date),
                         self.today + timedelta(days=35))

    def test_repeated_dispatch_preserves_skipped_and_completed_orders(self):
        self.order(status='skipped')
        self.order(days=-7, status='completed')
        self.plan.start_date -= timedelta(days=7)
        self.plan.save()
        self.dispatch()
        self.dispatch()
        self.assertEqual(self.plan.generated_orders.count(), 2)
        self.assertEqual(set(self.plan.generated_orders.values_list('status', flat=True)),
                         {'skipped', 'completed'})

    def test_dry_run_neither_backfills_assignment_nor_creates_orders(self):
        gwo = self.order(days=-7)
        self.dispatch(dry_run=True)
        gwo.refresh_from_db()
        self.plan.refresh_from_db()
        self.assertIsNone(gwo.crew_id)
        self.assertIsNone(self.plan.last_generated_date)
        self.assertEqual(self.plan.generated_orders.count(), 1)

    def test_backfills_crew_when_no_new_dates_exist_without_changing_history(self):
        gwo = self.order()
        history = self.order(days=-7, status='completed')
        self.dispatch()
        gwo.refresh_from_db()
        history.refresh_from_db()
        self.assertEqual(gwo.crew_id, self.crew.id)
        self.assertIsNone(history.crew_id)

    def test_disabled_jobplan_does_not_dispatch(self):
        self.job.active = False
        self.job.save()
        self.dispatch()
        self.assertFalse(self.plan.generated_orders.exists())

    def test_inactive_leader_is_replaced_by_active_member(self):
        self.worker.active = False
        self.worker.save()
        member = Worker.objects.create(employee_id='PM-W2', full_name='Active member')
        self.crew.members.add(member)
        self.dispatch()
        self.assertEqual(self.plan.generated_orders.get().worker_id, member.id)

    def test_inactive_crew_does_not_receive_orders(self):
        self.crew.active = False
        self.crew.save()
        self.dispatch()
        self.assertFalse(self.plan.generated_orders.exists())

    def test_zero_frequency_fails_without_hanging_and_other_plans_still_dispatch(self):
        MaintenancePlan.objects.create(
            pm_number='A-BAD', job_plan=self.job, frequency_value=0,
            frequency_unit='days', start_date=self.today, lead_days=0)
        with self.assertLogs('core.management.commands.generate_pm_workorders', level='ERROR'):
            with self.assertRaises(CommandError):
                self.dispatch()
        self.assertEqual(self.plan.generated_orders.count(), 1)

    def test_competing_dispatch_does_not_overwrite_or_fail_existing_order(self):
        def competing_dispatch(plan, zones):
            self.order(status='skipped')
            return self.worker
        with patch.object(Command, '_resolve_worker', side_effect=competing_dispatch):
            output = self.dispatch()
        self.assertIn('0 generated', output)
        self.assertEqual(self.plan.generated_orders.get().status, 'skipped')
        self.assertFalse(self.plan.generated_orders.get().zones.exists())

    def test_uncovered_land_is_not_ignored_by_auto_assignment(self):
        first = Land.objects.create(name='Covered')
        second = Land.objects.create(name='Uncovered')
        self.crew.lands.add(first)
        self.zone.land = first
        self.zone.save()
        zone2 = Zone.objects.create(code='PM-Z2', name='Other', land=second)
        self.plan.zones.add(zone2)
        self.plan.crew = None
        self.plan.save()
        call_command('assign_pm_crews', stdout=StringIO())
        self.plan.refresh_from_db()
        self.assertIsNone(self.plan.crew_id)


class PMDeadlineTests(PMFixture):
    def test_day_week_and_calendar_month_deadlines(self):
        for unit, value, start, end in [
            ('days', 2, date(2026, 10, 1), date(2026, 10, 3)),
            ('weeks', 3, date(2026, 10, 1), date(2026, 10, 22)),
            ('months', 1, date(2026, 1, 31), date(2026, 2, 28)),
            ('months', 12, date(2024, 2, 29), date(2025, 2, 28)),
        ]:
            with self.subTest(unit=unit, value=value, start=start):
                self.plan.frequency_unit, self.plan.frequency_value = unit, value
                self.assertEqual(completion_deadline(self.plan, start), end)

    def test_full_cycle_and_deadline_day_are_not_overdue(self):
        current = self.order(days=-1)
        deadline = self.order(days=-7)
        expired = self.order(days=-8)
        self.assertFalse(is_overdue(current, self.today))
        self.assertFalse(is_overdue(deadline, self.today))
        self.assertTrue(is_overdue(expired, self.today))
        for status in ['completed', 'skipped', 'pending']:
            expired.status = status
            self.assertFalse(is_overdue(expired, self.today))

    def test_mark_command_uses_full_cycle_and_keeps_closed_orders(self):
        current = self.order(days=-1)
        deadline = self.order(days=-7)
        expired = self.order(days=-8)
        skipped = self.order(days=-9, status='skipped')
        completed = self.order(days=-10, status='completed')
        call_command('mark_pm_overdue', date=self.today.isoformat(), stdout=StringIO())
        for obj, status in [(current, 'dispatched'), (deadline, 'dispatched'),
                            (expired, 'overdue'), (skipped, 'skipped'), (completed, 'completed')]:
            obj.refresh_from_db()
            self.assertEqual(obj.status, status)

    def test_task_list_and_notification_share_deadline_and_direct_assignment_visibility(self):
        current = self.order(days=-1)
        expired = self.order(days=-8)
        with patch('django.utils.timezone.localdate', return_value=self.today):
            visible = _pm_gwo_queryset(self.user, False)
            self.assertEqual(set(visible.values_list('id', flat=True)), {current.id, expired.id})
            tasks = _serialize_pm_tasks(visible, False)
            popup = pm_tasks_for_field_worker(self.user)
        expected = {current.id: False, expired.id: True}
        self.assertEqual({t['gwo_id']: t['overdue'] for t in tasks}, expected)
        self.assertEqual({t['gwo_id']: t['overdue'] for t in popup}, expected)


class PMSkipTests(PMFixture):
    def setUp(self):
        self.client.force_login(self.manager)
        self.date_patch = patch('django.utils.timezone.localdate', return_value=self.today)
        self.date_patch.start()
        self.addCleanup(self.date_patch.stop)

    def test_bulk_skip_handles_displayed_dispatched_and_overdue_only_after_cycle(self):
        expired = self.order(days=-8)
        old = self.order(days=-9, status='overdue')
        current = self.order(days=-1)
        deadline = self.order(days=-7)
        future = self.order(days=1)
        completed = self.order(days=-10, status='completed')
        skipped = self.order(days=-11, status='skipped')
        pending = self.order(days=-12, status='pending')
        response = self.post('pm_gwo_skip_all')
        self.assertEqual(response.json()['count'], 2)
        for obj, status in [(expired, 'skipped'), (old, 'skipped'), (current, 'dispatched'),
                            (deadline, 'dispatched'), (future, 'dispatched'),
                            (completed, 'completed'), (skipped, 'skipped'), (pending, 'pending')]:
            obj.refresh_from_db()
            self.assertEqual(obj.status, status)
        self.assertEqual(self.post('pm_gwo_skip_all').json()['count'], 0)

    def test_bulk_skip_all_120_orders_and_page_displays_actual_total(self):
        GeneratedWorkOrder.objects.bulk_create([
            GeneratedWorkOrder(plan=self.plan, scheduled_date=self.today - timedelta(days=i))
            for i in range(8, 128)
        ])
        response = self.client.get(reverse('core:pm_management'), {'tab': 'completion'},
                                   HTTP_HOST='127.0.0.1')
        self.assertEqual(response.context['overdue_count'], 120)
        self.assertEqual(len(response.context['overdue_orders']), 100)
        self.assertEqual(self.post('pm_gwo_skip_all').json()['count'], 120)

    def test_skipping_closes_only_related_pending_extensions(self):
        expired = self.order(days=-8)
        current = self.order(days=-1)
        ext = ExtensionRequest.objects.create(
            gwo=expired, requested_date=self.today, reason='Later')
        other = ExtensionRequest.objects.create(
            gwo=current, requested_date=self.today, reason='Later')
        self.post('pm_gwo_skip_all')
        ext.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(ext.status, 'rejected')
        self.assertEqual(ext.reviewed_by_id, self.manager.id)
        self.assertEqual(other.status, 'pending')

    def test_single_skip_cannot_overwrite_completed_or_skipped(self):
        for days, status in [(-8, 'completed'), (-9, 'skipped')]:
            gwo = self.order(days=days, status=status)
            response = self.post('pm_gwo_skip', [gwo.id])
            self.assertEqual(response.status_code, 400)
            gwo.refresh_from_db()
            self.assertEqual(gwo.status, status)

    def test_bulk_skip_requires_manager_and_post(self):
        gwo = self.order(days=-8)
        url = reverse('core:pm_gwo_skip_all')
        self.assertEqual(self.client.get(url, HTTP_HOST='127.0.0.1').status_code, 405)
        self.client.force_login(self.user)
        self.assertEqual(self.post('pm_gwo_skip_all').status_code, 403)
        gwo.refresh_from_db()
        self.assertEqual(gwo.status, 'dispatched')

    def test_chart_matches_list_and_removes_skipped_orders(self):
        self.order(days=-8)
        self.order(days=-1)
        self.order(days=-9, status='skipped')
        self.order(days=-10, status='completed')
        self.order(days=-11, status='pending')
        self.order()
        url = reverse('core:pm_completion_chart')
        response = self.client.get(url, HTTP_HOST='127.0.0.1')
        self.assertEqual(response.json()['total'], 1)
        self.post('pm_gwo_skip_all')
        self.assertEqual(self.client.get(url, HTTP_HOST='127.0.0.1').json()['total'], 0)

    def test_month_end_cycle_is_eligible_for_bulk_skip_only_after_deadline(self):
        self.plan.frequency_unit = 'months'
        self.plan.save()
        gwo = GeneratedWorkOrder.objects.create(plan=self.plan, scheduled_date=date(2026, 1, 31))
        with patch('django.utils.timezone.localdate', return_value=date(2026, 2, 28)):
            self.assertEqual(self.post('pm_gwo_skip_all').json()['count'], 0)
        with patch('django.utils.timezone.localdate', return_value=date(2026, 3, 1)):
            self.assertEqual(self.post('pm_gwo_skip_all').json()['count'], 1)
        gwo.refresh_from_db()
        self.assertEqual(gwo.status, 'skipped')

    def test_manual_generate_does_not_report_success_after_partial_failure(self):
        with patch('django.core.management.call_command', side_effect=CommandError('failed')):
            with self.assertLogs('core.views', level='ERROR'):
                response = self.client.post(reverse('core:pm_generate_now'),
                    HTTP_HOST='127.0.0.1', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertFalse(response.json()['success'])

    def test_extension_approval_cannot_reopen_skipped_or_completed_order(self):
        for days, status in [(-8, 'skipped'), (-9, 'completed')]:
            gwo = self.order(days=days, status=status)
            ext = ExtensionRequest.objects.create(
                gwo=gwo, reason='Later', requested_date=self.today + timedelta(days=30))
            response = self.post('pm_extension_approve', [ext.id])
            self.assertEqual(response.status_code, 400)
            gwo.refresh_from_db()
            self.plan.refresh_from_db()
            self.assertEqual(gwo.status, status)
            self.assertEqual(self.plan.start_date, self.today)

    def test_extension_approval_rolls_back_skip_when_reanchor_fails(self):
        gwo = self.order(days=-8)
        ext = ExtensionRequest.objects.create(
            gwo=gwo, reason='Later', requested_date=self.today + timedelta(days=30))
        with patch.object(MaintenancePlan, 'save', side_effect=RuntimeError('save failed')):
            with self.assertRaises(RuntimeError):
                self.post('pm_extension_approve', [ext.id])
        gwo.refresh_from_db()
        ext.refresh_from_db()
        self.assertEqual(gwo.status, 'dispatched')
        self.assertEqual(ext.status, 'pending')


class PMPlanScheduleTests(PMFixture):
    def setUp(self):
        self.client.force_login(self.manager)

    def save_plan(self, data, edit=False):
        fields = {'pm_number': 'PM-NEW', 'job_plan': self.job.id, 'crew': self.crew.id,
                  'frequency_value': '1', 'frequency_unit': 'weeks', 'lead_days': '0',
                  'active': 'on', 'zones': [self.zone.id]}
        fields.update(data)
        url = reverse('core:pm_plan_edit', args=[self.plan.id]) if edit else reverse('core:pm_plan_new')
        return self.client.post(url, fields, HTTP_HOST='127.0.0.1',
                                HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def test_new_plan_honors_anchor_date_and_zero_lead_days(self):
        response = self.save_plan({'start_date': '2026-11-01'})
        self.assertTrue(response.json()['success'])
        plan = MaintenancePlan.objects.get(pm_number='PM-NEW')
        self.assertEqual(plan.start_date, date(2026, 11, 1))
        self.assertEqual(plan.lead_days, 0)

    def test_invalid_schedule_rejected_without_creating_or_changing_plan(self):
        for edit in [False, True]:
            for fields in [{'frequency_value': '0'}, {'frequency_value': 'abc'},
                           {'lead_days': '-1'}, {'frequency_unit': 'years'},
                           {'start_date': 'bad-date'}]:
                with self.subTest(edit=edit, fields=fields):
                    response = self.save_plan(fields, edit=edit)
                    self.assertEqual(response.status_code, 400)
                    self.assertFalse(response.json()['success'])
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.pm_number, 'PM-TEST')
        self.assertEqual(self.plan.frequency_value, 1)
        self.assertEqual(self.plan.lead_days, 0)
        self.assertFalse(MaintenancePlan.objects.filter(pm_number='PM-NEW').exists())

    def test_edit_preserves_existing_dispatch_and_zero_lead_days(self):
        gwo = self.order(status='skipped')
        response = self.save_plan({'start_date': '2026-11-01'}, edit=True)
        self.assertTrue(response.json()['success'])
        self.plan.refresh_from_db()
        gwo.refresh_from_db()
        self.assertEqual(self.plan.start_date, date(2026, 11, 1))
        self.assertEqual(self.plan.lead_days, 0)
        self.assertEqual(gwo.scheduled_date, self.today)
        self.assertEqual(gwo.status, 'skipped')
