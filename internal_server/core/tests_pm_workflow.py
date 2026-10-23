"""End-to-end regressions for PM assignment and both work-order save paths."""
import json
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.urls import reverse

from core.models import (
    GeneratedWorkOrder, PMWorkOrder, WorkItem, WorkReport, WorkReportEntry,
    Worker, Zone, Project, Patch, JobPlanTemplate, MaintenancePlan, Satellite, Crew,
)
from core.tests_pm import PMFixture
from core.views import _serialize_pm_tasks


class PMWorkOrderFlowTests(PMFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        root = WorkItem.objects.create(code='1', name_zh='常规维护', section='routine_maint', value_type='group')
        parent = WorkItem.objects.create(code='1.2', name_zh='维保定期检查', parent=root,
                                         section='routine_maint', value_type='group')
        cls.leaf = WorkItem.objects.create(code='1.2.pm', name_zh='PM作业计划', parent=parent,
                                           section='routine_maint', value_type='text')

    def setUp(self):
        self.client.force_login(self.user)
        clock = patch('django.utils.timezone.localdate', return_value=self.today)
        clock.start()
        self.addCleanup(clock.stop)

    def task(self, **kwargs):
        order = self.order(crew=self.crew, **kwargs)
        order.zones.add(self.zone)
        return order

    def submit(self, order, *, desktop=False, **extra):
        fields = {'date': self.today.isoformat(), 'gwo_id': order.pk,
                  'zones': [self.zone.code], 'entries': '[]', 'team_size': '1'}
        fields.update(extra)
        return self.client.post(reverse('core:workorder_tree_form' if desktop else 'core:workorder_mobile_v2'),
                                fields, HTTP_HOST='127.0.0.1', HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def test_new_pm_seed_has_job_category_deadline_extension_and_actual_work_date(self):
        order = self.task(days=-2)
        data = self.client.get(reverse('core:pm_gwo_detail', args=[order.pk]), HTTP_HOST='127.0.0.1').json()
        self.assertEqual(data['header']['h_pm_work_item'], self.leaf.pk)
        self.assertEqual(data['header']['h_pm_job_plan'], self.job.name)
        self.assertEqual(data['header']['h_date'], self.today.isoformat())
        self.assertEqual(data['header']['h_pm_deadline'], order.deadline.isoformat())
        self.assertTrue(data['header']['h_pm_can_extend'])

    def test_completion_records_job_plan_even_when_client_omits_entries(self):
        order = self.task()
        self.assertTrue(self.submit(order).json()['success'])
        record = PMWorkOrder.objects.get(gwo=order)
        self.assertEqual(record.entries.get(work_item=self.leaf).text_value, self.job.name)
        self.assertEqual(WorkReport.objects.count(), 0)

    def test_pm_completion_rejects_future_or_pre_schedule_work_dates(self):
        order = self.task()
        for delta in (-1, 1):
            response = self.submit(order, date=(self.today + timedelta(days=delta)).isoformat())
            self.assertEqual(response.status_code, 400)
        self.assertFalse(PMWorkOrder.objects.exists())
        order.refresh_from_db()
        self.assertEqual(order.status, 'dispatched')

    def test_pm_completion_requires_the_dispatched_asset_scope(self):
        order = self.task()
        other = Zone.objects.create(code='OTHER-PM', name='Other scope')
        for zones in ([], [other.code], [self.zone.code, other.code]):
            response = self.submit(order, zones=zones)
            self.assertEqual(response.status_code, 400)
        self.assertFalse(PMWorkOrder.objects.exists())

    def test_invalid_or_conflicting_owner_ids_do_not_create_another_kind_of_order(self):
        order = self.task()
        for extra in ({'pm_order_id': 'bad'}, {'report_id': 'bad'}, {'report_id': '123'},
                      {'pm_order_id': '1', 'report_id': '1'}, {'merge_dup_ids': '1,2'}):
            response = self.submit(order, **extra)
            self.assertEqual(response.status_code, 400)
        self.assertFalse(PMWorkOrder.objects.exists())
        self.assertFalse(WorkReport.objects.exists())

    def test_pm_form_can_save_project_entries_without_workreport_only_fields(self):
        order = self.task()
        project = Project.objects.create(name='PM associated project')
        entries = json.dumps([{'work_item': self.leaf.pk, 'text_value': 'Checked', 'project': project.pk}])
        response = self.submit(order, entries=entries)
        self.assertTrue(response.json()['success'], response.content)
        self.assertEqual(PMWorkOrder.objects.count(), 1)

    def test_edit_preserves_pm_entry_text_and_photos_and_hides_extension_for_closed_task(self):
        order = self.task()
        record = PMWorkOrder.objects.create(gwo=order, worker=self.worker, date=self.today)
        record.zones.add(self.zone)
        order.pm_order, order.status = record, 'completed'
        order.save(update_fields=['pm_order', 'status'])
        WorkReportEntry.objects.create(pm_work_order=record, work_item=self.leaf,
                                       text_value='Valve leak found and repaired', photos=['workorder_photos/old.jpg'])
        entries = json.dumps([{'work_item': self.leaf.pk, 'text_value': 'Valve leak found and repaired'}])
        response = self.submit(order, pm_order_id=record.pk, entries=entries)
        self.assertTrue(response.json()['success'], response.content)
        entry = record.entries.get()
        self.assertEqual(entry.photos, ['workorder_photos/old.jpg'])
        self.assertEqual(entry.text_value, 'Valve leak found and repaired')
        data = self.client.get(reverse('core:workorder_modal_data'), {'pm_order_id': record.pk},
                               HTTP_HOST='127.0.0.1').json()
        self.assertFalse(data['header']['h_pm_can_extend'])

    def test_completed_task_list_shows_actual_executor_instead_of_crew_leader(self):
        member = Worker.objects.create(employee_id='PM-MEMBER', full_name='Actual executor')
        order = self.task()
        record = PMWorkOrder.objects.create(gwo=order, worker=member, date=self.today)
        order.pm_order, order.status = record, 'completed'
        order.save(update_fields=['pm_order', 'status'])
        self.assertEqual(_serialize_pm_tasks([order], True)[0]['worker_name'], member.full_name)

    def test_desktop_invalid_upload_does_not_leave_an_orphan_that_blocks_completion(self):
        order = self.task()
        bad = SimpleUploadedFile('bad.txt', b'not a photo', content_type='text/plain')
        response = self.submit(order, desktop=True, report_photos=bad)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(PMWorkOrder.objects.exists())
        order.refresh_from_db()
        self.assertEqual(order.status, 'dispatched')
        self.assertEqual(self.submit(order, desktop=True).status_code, 302)

    def test_desktop_pm_success_opens_pm_record_and_never_regular_report_with_same_id(self):
        order = self.task()
        response = self.submit(order, desktop=True)
        record = PMWorkOrder.objects.get(gwo=order)
        self.assertEqual(response.url, reverse('core:dashboard') + f'?pm_order_id={record.pk}')

    def test_missing_zone_patch_does_not_assign_an_unrelated_ccu(self):
        Patch.objects.create(code='UNRELATED-PATCH', name='Unrelated CCU')
        order = self.task()
        response = self.submit(order)
        self.assertTrue(response.json()['success'])
        self.assertIsNone(PMWorkOrder.objects.get(gwo=order).location_id)

    def test_seed_work_items_repairs_missing_pm_leaf_after_migrations_already_ran(self):
        self.leaf.delete()
        call_command('seed_work_items', stdout=StringIO())
        self.assertTrue(WorkItem.objects.filter(code='1.2.pm', active=True).exists())

    def test_foreign_photo_removal_path_cannot_delete_another_orders_file(self):
        order = self.task()
        self.assertTrue(self.submit(order).json()['success'])
        record = PMWorkOrder.objects.get(gwo=order)
        record.photos = ['workorder_photos/pm/owned.jpg']
        record.save(update_fields=['photos'])
        with patch('core.workorder_tree_views._delete_media') as delete:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.submit(order, pm_order_id=record.pk,
                                       report_photos_remove='workorder_photos/other.jpg')
            self.assertTrue(response.json()['success'])
            delete.assert_not_called()
        record.refresh_from_db()
        self.assertEqual(record.photos, ['workorder_photos/pm/owned.jpg'])

    def test_both_forms_reject_bad_json_and_numbers_before_creating_records(self):
        order = self.task()
        for desktop in (False, True):
            for fields in ({'entries': '{}'}, {'entries': 'invalid'}, {'materials': '[1]'},
                           {'team_size': '-1'}, {'third_party_count': '-2'},
                           {'entries': json.dumps([{'work_item': self.leaf.pk, 'count': -1}])}):
                response = self.submit(order, desktop=desktop, **fields)
                self.assertEqual(response.status_code, 400)
        self.assertFalse(PMWorkOrder.objects.exists())

    def test_dashboard_pm_data_escapes_script_tags_and_keeps_single_authoritative_payload(self):
        import re
        self.job.name = '</script><script>alert(1)</script>'
        self.job.save(update_fields=['name'])
        order = self.task()
        response = self.client.get(reverse('core:dashboard'), HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '</script><script>alert(1)</script>')
        html = response.content.decode()
        self.assertEqual(html.count('id="pm-tasks-data"'), 1)
        data = re.search(r'<script id="pm-tasks-data" type="application/json">(.*?)</script>', html, re.S)
        payload = json.loads(data.group(1))
        self.assertEqual(payload[0]['job_plan_name'], self.job.name)
        self.assertEqual(payload[0]['gwo_id'], order.pk)
        self.assertEqual(payload[0]['deadline'], order.deadline.isoformat())
        self.assertIn('openV2ModalForPm(gwoId)', html)
        self.assertIn('var fillBtn = t.gwo_id', html)

    def test_outside_worker_cannot_read_or_edit_a_completed_pm_record(self):
        from django.contrib.auth.models import User
        order = self.task()
        self.assertTrue(self.submit(order).json()['success'])
        record = PMWorkOrder.objects.get(gwo=order)
        outside = User.objects.create_user('outside-pm-review')
        Worker.objects.create(user=outside, employee_id='OUT-PM-REVIEW', full_name='Outside worker')
        self.client.force_login(outside)
        response = self.client.get(reverse('core:workorder_modal_data'), {'pm_order_id': record.pk},
                                   HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 404)
        response = self.submit(order, pm_order_id=record.pk, remark='Unauthorized edit')
        self.assertFalse(response.json()['success'])
        record.refresh_from_db()
        self.assertNotEqual(record.remark, 'Unauthorized edit')


class PMAssetAssignmentTests(PMFixture):
    def test_ccu_and_satellite_dispatch_use_the_target_ccu_crew_and_snapshot_zones(self):
        patch = Patch.objects.create(code='CCU901', name='Review CCU')
        self.zone.patch = patch
        self.zone.save()
        satellite = Satellite.objects.create(code='901-1', patch=patch)
        satellite.zones.add(self.zone)
        self.crew.patches.add(patch)
        for level in ('ccu', 'sat'):
            job = JobPlanTemplate.objects.create(name='Asset review ' + level, asset_level=level)
            plan = MaintenancePlan.objects.create(pm_number='ASSET-' + level, job_plan=job,
                patch=patch if level == 'ccu' else None,
                satellite=satellite if level == 'sat' else None, start_date=self.today,
                frequency_unit='months', lead_days=0)
            self.dispatch()
            order = plan.generated_orders.get()
            self.assertEqual(order.crew_id, self.crew.pk)
            self.assertEqual(list(order.zones.all()), [self.zone])
            self.assertEqual(order.deadline.month, self.today.month + 1)
            plan.active = False
            plan.save(update_fields=['active'])

    def test_asset_form_discards_irrelevant_links_and_rejects_missing_real_scope(self):
        from core.pm_forms import MaintenancePlanForm
        patch = Patch.objects.create(code='CCU902', name='Review CCU 2')
        satellite = Satellite.objects.create(code='902-1', patch=patch)
        for level in ('ccu', 'sat', 'zone_group'):
            job = JobPlanTemplate.objects.create(name='Form review ' + level, asset_level=level)
            form = MaintenancePlanForm({
                'pm_number': 'FORM-' + level, 'job_plan': job.pk, 'active': 'on',
                'frequency_value': 1, 'frequency_unit': 'months', 'lead_days': 0,
                'patch': patch.pk, 'satellite': satellite.pk, 'zones': [self.zone.pk],
            }, default_start=self.today)
            self.assertTrue(form.is_valid(), form.errors)
            plan = form.save()
            self.assertEqual(plan.patch_id is not None, level == 'ccu')
            self.assertEqual(plan.satellite_id is not None, level == 'sat')
            self.assertEqual(plan.zones.exists(), level == 'zone_group')

    def test_auto_assignment_reports_disabled_explicit_crew(self):
        self.crew.active = False
        self.crew.save(update_fields=['active'])
        output = StringIO()
        call_command('assign_pm_crews', stdout=output)
        self.assertIn('负责班组已停用', output.getvalue())
        self.assertIn('1 no matching crew', output.getvalue())

    def test_issued_ccu_task_keeps_original_asset_label_after_plan_asset_changes(self):
        original = Patch.objects.create(code='CCU903', name='Issued asset')
        replacement = Patch.objects.create(code='CCU904', name='Replacement asset')
        self.zone.patch = original
        self.zone.save()
        job = JobPlanTemplate.objects.create(name='Snapshot review', asset_level='ccu')
        plan = MaintenancePlan.objects.create(pm_number='ASSET-SNAPSHOT', job_plan=job,
            patch=original, crew=self.crew, start_date=self.today)
        order = GeneratedWorkOrder.objects.create(plan=plan, crew=self.crew, scheduled_date=self.today)
        order.zones.add(self.zone)
        plan.patch = replacement
        plan.save(update_fields=['patch'])
        self.assertIn('CCU903', _serialize_pm_tasks([order], True)[0]['area_desc'])
        self.assertNotIn('CCU904', _serialize_pm_tasks([order], True)[0]['area_desc'])
