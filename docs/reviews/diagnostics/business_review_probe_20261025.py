"""Diagnostic probes of CURRENT defects, using an isolated Django test database.

Assertions deliberately describe observed behavior, not desired production behavior.
Never run against production; no external model, email, or network is invoked.
"""
import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
(ROOT / '.tmp-pm-review').mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT / 'internal_server'))
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
os.environ['DEBUG'] = 'True'
os.environ['SECRET_KEY'] = 'isolated-business-audit-only'
from django.conf import settings
settings.CACHES = {key: {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}
                   for key in ('default', 'dxffile')}
settings.DATABASES['default']['TEST'] = {'NAME': ':memory:'}
settings.ALLOWED_HOSTS = ['testserver', 'localhost']
import django
django.setup()

from django.contrib.auth.models import User
from django.core.exceptions import FieldError
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.runner import DiscoverRunner
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from core import views
from core.models import (AISettings, DepartmentUserProfile, EmailReportConfig, InventoryCategory,
    InventoryTransaction, InventoryTransactionLine, ManagerProfile, Patch,
    Project, PurchaseOrder, PurchaseOrderLine, RegistrationRequest, WaterRequest,
    Worker, WorkReport, Zone)
from core.workorder_tree_views import _project_budget_data

EVIDENCE = {}


class AuditProbes(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('audit-admin', is_staff=True)
        self.owner = User.objects.create_user('audit-owner')
        self.other = User.objects.create_user('audit-other')
        self.dept = User.objects.create_user('audit-dept')
        self.worker = Worker.objects.create(user=self.owner, employee_id='AUD-1', full_name='A Worker')
        self.worker_b = Worker.objects.create(user=self.other, employee_id='AUD-2', full_name='Z Worker')
        DepartmentUserProfile.objects.create(user=self.dept, employee_id='AUD-D', full_name='Dept')
        self.cat = InventoryCategory.objects.create(code='AUD-C', name_zh='Valve', current_stock=100)
        self.zone = Zone.objects.create(code='AUD-Z', name='Audit Zone')
        self.today = timezone.localdate()
        self.client.force_login(self.admin)

    def txn(self, **kw):
        values = dict(worker=self.worker, operation='出库', entry_subtype='项目',
                      consumption_mode='actual', confirm_status='pending', date=self.today)
        values.update(kw)
        t = InventoryTransaction.objects.create(**values)
        InventoryTransactionLine.objects.create(transaction=t, category=self.cat, quantity=5)
        return t

    def test_api_workreports_deleted_relation(self):
        WorkReport.objects.create(worker=self.worker, date=self.today)
        with self.assertRaises(FieldError) as error:
            self.client.get('/api/work-reports/')
        EVIDENCE['api_workreports'] = str(error.exception)

    def test_zone_patch_clears_boundary(self):
        points = [{'lat': 31.1, 'lng': 121.1}, {'lat': 31.2, 'lng': 121.1},
                  {'lat': 31.2, 'lng': 121.2}, {'lat': 31.1, 'lng': 121.1}]
        self.zone.boundary_points = points
        self.zone.save()
        c = APIClient()
        c.force_authenticate(self.admin)
        response = c.patch(f'/api/zones/{self.zone.pk}/', {'name': 'Renamed'}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.boundary_points, [])
        EVIDENCE['zone_partial_update'] = {'status': 200, 'before_points': len(points), 'after_points': 0}

    def test_zone_geo_requires_both_sources(self):
        points = [{'lat': 31.1, 'lng': 121.1}, {'lat': 31.2, 'lng': 121.1},
                  {'lat': 31.2, 'lng': 121.2}, {'lat': 31.1, 'lng': 121.1}]
        self.zone.boundary_points = points
        self.zone.save()
        response = self.client.get('/api/zone-geo/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.zone.code, [z['c'] for z in response.json()])
        EVIDENCE['zone_geo'] = {'valid_manual_boundary': True, 'returned_zones': response.json()}

    def test_department_can_edit_another_workreport(self):
        report = WorkReport.objects.create(worker=self.worker, date=self.today, remark='Original')
        self.client.force_login(self.dept)
        response = self.client.post(reverse('core:workorder_tree_form_edit', args=[report.pk]), {
            'date': self.today.isoformat(), 'remark': 'Changed by department user',
            'entries': '[]', 'materials': '[]', 'team_size': 1})
        self.assertEqual(response.status_code, 302)
        report.refresh_from_db()
        self.assertEqual(report.remark, 'Changed by department user')
        EVIDENCE['workreport_edit_acl'] = {'department_edits_other_worker': True, 'status': 302}

    def test_water_request_owner_can_approve(self):
        wr = WaterRequest.objects.create(submitter=self.worker, zone=self.zone,
            start_datetime=timezone.now(), end_datetime=timezone.now()+timedelta(hours=1))
        c = APIClient()
        c.force_authenticate(self.worker)
        response = c.patch(f'/api/water-requests/{wr.pk}/', {'status': 'approved'}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        wr.refresh_from_db()
        self.assertEqual(wr.status, 'approved')
        EVIDENCE['water_self_approval'] = {'status': wr.status, 'approver_id': wr.approver_id, 'processed_at': str(wr.processed_at)}

    def test_worker_edits_foreign_confirmed_inventory(self):
        t = self.txn(confirm_status='confirmed')
        self.cat.current_stock = 95
        self.cat.save()
        self.client.force_login(self.other)
        response = self.client.post('/mobile/inventory/v2/', {
            'txn_id': t.pk, 'operation': '出库', 'entry_subtype': '项目',
            'date': self.today.isoformat(), 'lines': json.dumps([{'category': self.cat.pk, 'quantity': 9}]),
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(response.json()['success'], response.content)
        t.refresh_from_db(); self.cat.refresh_from_db()
        self.assertEqual(t.confirm_status, 'confirmed')
        self.assertEqual(self.cat.current_stock, 91)
        EVIDENCE['inventory_edit_acl'] = {'other_worker_changed_confirmed_txn': True, 'stock': 91, 'confirmation': t.confirm_status}

    def test_worker_voids_foreign_estimate(self):
        t = self.txn(consumption_mode='estimated')
        self.client.force_login(self.other)
        response = self.client.post(reverse('core:inventory_estimate_void', args=[t.pk]))
        self.assertTrue(response.json()['success'])
        self.assertFalse(InventoryTransaction.objects.filter(pk=t.pk).exists())
        EVIDENCE['inventory_estimate_acl'] = {'other_worker_deleted_estimate': True}

    def test_project_counts_pending_transaction(self):
        project = Project.objects.create(name='Audit Project')
        self.txn(related_project=project)
        data = _project_budget_data([project])[project.pk]
        self.assertEqual(data['material_consumed'][0]['qty'], 5)
        self.cat.refresh_from_db()
        self.assertEqual(self.cat.current_stock, 100)
        EVIDENCE['project_pending_count'] = {'counted_qty': 5, 'ledger_status': 'pending', 'stock': 100}

    def test_po_can_complete_with_removed_receipt(self):
        po = PurchaseOrder.objects.create(order_number='AUD-PO')
        PurchaseOrderLine.objects.create(purchase_order=po, category=self.cat, quantity=5)
        self.txn(operation='入库', entry_subtype='采购', confirm_status='removed', purchase_order=po)
        response = self.client.post(reverse('core:purchase_order_complete', args=[po.pk]))
        self.assertTrue(response.json()['success'], response.content)
        po.refresh_from_db()
        self.assertTrue(po.is_completed)
        EVIDENCE['po_removed_receipt'] = {'completed': True, 'receipt_status': 'removed'}

    def test_worker_sort_loses_next_page(self):
        size = views.WORK_REPORTS_PAGE_SIZE
        WorkReport.objects.bulk_create([WorkReport(worker=self.worker, date=self.today) for _ in range(size)])
        missed = WorkReport.objects.create(worker=self.worker_b, date=self.today)
        response = self.client.get('/work-reports/', {'sort': 'worker', 'ajax': '1'})
        first = response.json()
        self.assertTrue(first['has_more'])
        second = self.client.get('/work-reports/', {'sort': 'worker', 'ajax': '1', 'before_id': first['last_id']}).json()
        ids = [r['id'] for r in first['reports']+second['reports']]
        self.assertNotIn(missed.pk, ids)
        EVIDENCE['workreport_cursor'] = {'rows': size+1, 'first': len(first['reports']), 'second': len(second['reports']), 'missed': missed.pk}

    def test_disabled_user_token_still_authenticates(self):
        from core.authentication import TokenAuthentication
        self.owner.is_active = False
        self.owner.save()
        authenticated, _ = TokenAuthentication().authenticate_credentials(str(self.worker.api_token))
        self.assertEqual(authenticated.pk, self.worker.pk)
        EVIDENCE['inactive_user_token'] = {'django_user_active': False, 'token_accepted': True}

    def test_ai_accepts_another_users_thread(self):
        AISettings.objects.create(enabled=True, api_base_url='https://invalid.example', api_key='fixture', model_name='fixture')
        other_thread = f'u{self.owner.pk}-abcdef12'
        with patch('core.ai_views._stream_via_queue', return_value=iter([])) as stream:
            response = self.client.post('/api/ai/chat', data=json.dumps({'message': 'fixture', 'thread_id': other_thread}), content_type='application/json')
            self.assertEqual(response.status_code, 200)
            list(response.streaming_content)
            stream.assert_called_once_with('fixture', other_thread)
        EVIDENCE['ai_thread_owner'] = {'another_user_thread_accepted': True}

    def test_any_login_downloads_ai_checkpoint_path(self):
        import config.urls
        media_pattern = next(p for p in config.urls.urlpatterns if str(p.pattern).startswith('^media/'))
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp-pm-review') as media:
            Path(media, 'ai_checkpoints.sqlite3').write_bytes(b'AUDIT-FAKE-CHECKPOINT')
            self.client.force_login(self.other)
            # urls.py binds MEDIA_ROOT at module import, so change the route's
            # document_root as well as settings; never read the real checkpoint.
            with override_settings(MEDIA_ROOT=media), patch.dict(media_pattern.default_args, document_root=media):
                response = self.client.get('/media/ai_checkpoints.sqlite3')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(b''.join(response.streaming_content), b'AUDIT-FAKE-CHECKPOINT')
        EVIDENCE['ai_checkpoint_media'] = {'field_worker_downloaded_fake_checkpoint': True, 'status': 200}

    def test_python_tool_reads_outside_workspace(self):
        from core.ai_agent import run_python_code
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp-pm-review') as root:
            workspace = Path(root, 'workspace'); workspace.mkdir()
            Path(root, 'outside.txt').write_text('AUDIT-SENTINEL', encoding='utf-8')
            with patch('core.ai_agent.ensure_workspace', return_value=str(workspace)):
                result = json.loads(run_python_code.func("from pathlib import Path\nprint(Path('../outside.txt').read_text())", runtime=SimpleNamespace(context={'thread_id': 'fixture'})))
            self.assertEqual(result['exit_code'], 0, result)
            self.assertIn('AUDIT-SENTINEL', result['stdout'])
        EVIDENCE['ai_python_isolation'] = {'read_parent_directory_sentinel': True, 'real_secrets_accessed': False}

    def test_approval_failure_leaves_orphan_user(self):
        from django.contrib.auth.hashers import make_password
        reg = RegistrationRequest.objects.create(username='audit-new', full_name='New', phone='000',
            employee_id=self.worker.employee_id, requested_role='field_worker', password=make_password('fixture'))
        # Isolate the request's inner savepoint so its expected IntegrityError
        # does not poison TestCase's outer transaction.
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.client.post('/user-management/', {'request_id': reg.pk, 'action': 'approve'})
        # The enclosing savepoint rolls it back for test cleanup. Verify the
        # endpoint creates a user before the failure with a manager-create probe.
        observed = []
        original = Worker.objects.create
        def fail_profile(**kwargs):
            observed.append(User.objects.filter(username='audit-new').exists())
            raise RuntimeError('AUDIT profile failure')
        with patch.object(Worker.objects, 'create', side_effect=fail_profile):
            with self.assertRaisesRegex(RuntimeError, 'AUDIT profile failure'):
                self.client.post('/user-management/', {'request_id': reg.pk, 'action': 'approve'})
        self.assertEqual(observed, [True])
        self.assertTrue(User.objects.filter(username='audit-new').exists())
        reg.refresh_from_db(); self.assertEqual(reg.status, 'pending')
        EVIDENCE['registration_atomicity'] = {'user_exists_after_profile_failure': True, 'request_status': 'pending'}

    def test_reverse_time_water_request_is_accepted(self):
        self.client.force_login(self.dept)
        response = self.client.post('/mobile/water-request/v2/', {
            'zone_codes': json.dumps([self.zone.code]), 'request_type': '停水需求',
            'start_datetime': '2026-10-25T18:00', 'end_datetime': '2026-10-25T06:00'})
        self.assertTrue(response.json()['success'], response.content)
        wr = WaterRequest.objects.latest('pk')
        self.assertGreater(wr.start_datetime, wr.end_datetime)
        EVIDENCE['water_reverse_time'] = {'accepted': True, 'end_before_start': True}

    def test_legacy_workrequest_dept_create_fails(self):
        c = APIClient(); c.force_authenticate(self.dept)
        with self.assertRaises(User.worker_profile.RelatedObjectDoesNotExist):
            c.post('/api/water-requests/', {'zones': [self.zone.pk],
                'start_datetime': '2026-10-25T06:00:00+08:00',
                'end_datetime': '2026-10-25T18:00:00+08:00',
                'user_type': 'ENT', 'request_type': '停水需求'}, format='json')
        EVIDENCE['water_api_dept'] = {'missing_worker_profile_causes_error': True}

    def test_approved_status_not_reset_on_foreign_edit(self):
        # Business-state evidence is captured in inventory_edit_acl above.
        # Reproduce fractional quantity balance drift through the public form.
        response = self.client.post('/mobile/inventory/v2/', {
            'operation': '出库', 'entry_subtype': '日常维护', 'date': self.today.isoformat(),
            'lines': json.dumps([{'category': self.cat.pk, 'quantity': 1.5}])},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTrue(response.json()['success'], response.content)
        t = InventoryTransaction.objects.latest('pk')
        quantity = t.lines.get().quantity
        with connection.cursor() as cursor:
            cursor.execute('SELECT current_stock FROM core_inventorycategory WHERE id=%s', [self.cat.pk])
            raw_stock = cursor.fetchone()[0]
        self.assertEqual(quantity, 1)
        self.assertEqual(raw_stock, 98.5)
        EVIDENCE['fractional_inventory'] = {'input': 1.5, 'stored_line': quantity, 'raw_stock': raw_stock, 'expected_from_stored_line': 99}

    def test_inventory_confirmation_stale_candidates_deduct_twice(self):
        t = self.txn()
        # Deterministic schedule: both requests SELECT pending before either
        # enters atomic(). Then their writes execute sequentially, as SQLite
        # would serialize writers. No timing assumptions or production load.
        stale_a = InventoryTransaction.objects.get(pk=t.pk)
        stale_b = InventoryTransaction.objects.get(pk=t.pk)
        with patch.object(InventoryTransaction.objects, 'filter', side_effect=[[stale_a], [stale_b]]):
            for _ in range(2):
                result = self.client.post('/inventory/txn/confirm/', {'txn_ids': [t.pk]})
                self.assertEqual(result.json()['count'], 1)
        self.cat.refresh_from_db()
        self.assertEqual(self.cat.current_stock, 90)
        EVIDENCE['inventory_confirmation_interleaving'] = {'schedule': 'two pending SELECTs, then two serialized writes', 'stored_quantity': 5, 'stock_after': 90, 'expected_stock': 95}

    def test_api_water_request_crashes_admin_html_context(self):
        from core.context_processors import notifications
        from django.test import RequestFactory
        c = APIClient(); c.force_authenticate(self.worker)
        response = c.post('/api/water-requests/', {'zones': [self.zone.pk],
            'start_datetime': '2026-10-25T06:00:00+08:00',
            'end_datetime': '2026-10-25T18:00:00+08:00',
            'user_type': 'ENT', 'request_type': '停水需求'}, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        request = RequestFactory().get('/profile/'); request.user = self.admin
        with self.assertRaisesRegex(AttributeError, 'name'):
            notifications(request)
        EVIDENCE['water_api_global_context'] = {'create_status': 201, 'legacy_zone_id': WaterRequest.objects.latest('pk').zone_id, 'admin_context_raises': 'AttributeError'}

    def test_email_partial_failure_reported_as_success(self):
        from io import BytesIO, StringIO
        from django.core.management import call_command
        cfg = EmailReportConfig.objects.create(name='Audit Mail', recipients='audit@example.invalid',
            report_types=['zones', 'irrigation'], send_hour=timezone.localtime().hour)
        attachments = [('fixture.xlsx', BytesIO(b'fixture'), '区域'), (None, None, 'FAILED:irrigation:fixture failure')]
        with patch('core.smtp_utils.is_smtp_configured', return_value=True), \
             patch('core.management.commands.send_report_email._build_all_attachments', return_value=attachments), \
             patch('core.smtp_utils.get_email_connection', return_value=None), \
             patch('core.smtp_utils.resolve_from_email', return_value='audit@example.invalid'), \
             patch('django.core.mail.EmailMessage.send', return_value=1) as send:
            call_command('send_report_email', stdout=StringIO())
            self.assertEqual(send.call_count, 1)
        cfg.refresh_from_db(); self.assertEqual(cfg.last_status, 'success')
        EVIDENCE['email_partial_failure'] = {'requested_attachments': 2, 'built': 1, 'failed': 1, 'recorded_status': cfg.last_status, 'real_emails_sent': 0}

    def test_email_due_rerun_sends_twice(self):
        from io import BytesIO, StringIO
        from django.core.management import call_command
        cfg = EmailReportConfig.objects.create(name='Audit Repeat', recipients='audit@example.invalid',
            report_types=['zones'], send_hour=timezone.localtime().hour)
        with patch('core.smtp_utils.is_smtp_configured', return_value=True), \
             patch('core.management.commands.send_report_email._build_all_attachments', side_effect=lambda *a, **k: [('fixture.xlsx', BytesIO(b'fixture'), '区域')]), \
             patch('core.smtp_utils.get_email_connection', return_value=None), \
             patch('core.smtp_utils.resolve_from_email', return_value='audit@example.invalid'), \
             patch('django.core.mail.EmailMessage.send', return_value=1) as send:
            for _ in range(2):
                call_command('send_report_email', stdout=StringIO())
            self.assertEqual(send.call_count, 2)
        EVIDENCE['email_duplicate_slot'] = {'runs_in_same_slot': 2, 'simulated_sends': 2, 'real_emails_sent': 0}

    def test_region_api_query_scaling(self):
        from core.models import Region
        region = Region.objects.create(name='Audit Region')
        for number in range(8):
            Patch.objects.create(code=f'AUD-P-{number}', name='Patch', region=region)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get('/api/patches/')
        self.assertEqual(response.status_code, 200)
        region_selects = [q['sql'] for q in queries if 'FROM "core_region"' in q['sql']]
        self.assertEqual(len(region_selects), 8)
        EVIDENCE['patch_api_n_plus_one'] = {'patches': 8, 'additional_region_queries': 8, 'total_queries': len(queries)}

    def test_department_can_delete_map_landmark(self):
        from core.models import Landmark
        lm = Landmark.objects.create(name='Audit Landmark')
        self.client.force_login(self.dept)
        response = self.client.post(reverse('core:landmark_delete', args=[lm.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Landmark.objects.filter(pk=lm.pk).exists())
        EVIDENCE['landmark_write_acl'] = {'department_user_deleted_map_landmark': True, 'status': 200}

    def test_landmark_assignment_ignores_active_dxf(self):
        from core.models import Landmark, ZoneLandmarkAssignment
        points = [{'lat': 31.1, 'lng': 121.1}, {'lat': 31.2, 'lng': 121.1},
                  {'lat': 31.2, 'lng': 121.2}, {'lat': 31.1, 'lng': 121.1}]
        self.zone.dxf_boundary_points = points; self.zone.boundary_source = 'dxf'; self.zone.save()
        lm = Landmark.objects.create(name='Audit DXF overlap', boundary_points=points)
        count = views._recalculate_landmark_assignments()
        self.assertEqual(count, 0)
        self.assertFalse(ZoneLandmarkAssignment.objects.filter(zone=self.zone, landmark=lm).exists())
        EVIDENCE['landmark_active_dxf'] = {'identical_active_zone_and_landmark_polygons': True, 'assignments': count}

    def test_settings_queries_each_patch(self):
        from django.http import HttpResponse
        from django.test import RequestFactory
        for number in range(12):
            Patch.objects.create(code=f'SCALE-{number}', name='Scale Patch')
        patch_count = Patch.objects.count()
        request = RequestFactory().get('/settings/?tab=zones'); request.user = self.admin
        with patch('core.views.render', return_value=HttpResponse('fixture')), CaptureQueriesContext(connection) as queries:
            response = views.settings_page(request)
        children_queries = [q['sql'] for q in queries if 'COUNT(*)' in q['sql'] and '"core_patch"."parent_id" =' in q['sql']]
        self.assertEqual(len(children_queries), patch_count)
        EVIDENCE['settings_n_plus_one'] = {'added_patches': 12, 'patches_including_migration_seeds': patch_count,
            'individual_child_count_queries': len(children_queries), 'total_view_queries_without_template': len(queries)}

    def test_worker_pwa_lists_unavailable_modules(self):
        from core.pwa import navigation
        from django.test import RequestFactory
        request = RequestFactory().get('/app/'); request.user = self.dept
        modules = {m['name'] for m in navigation(request)['pwa_modules']}
        self.assertIn('inventory_management', modules)
        self.client.force_login(self.dept)
        response = self.client.get('/inventory/manage/')
        self.assertEqual(response.status_code, 302)
        EVIDENCE['pwa_role_navigation'] = {'department_offered_inventory': True, 'destination_status': 302, 'redirect': response.url}


if __name__ == '__main__':
    runner = DiscoverRunner(verbosity=2)
    result = runner.run_tests(['__main__.AuditProbes'])
    path = ROOT / '.tmp-pm-review/business-audit-evidence.json'
    path.write_text(json.dumps(EVIDENCE, ensure_ascii=False, indent=2), encoding='utf-8')
    print('AUDIT_EVIDENCE', path, 'probes', len(EVIDENCE), flush=True)
    sys.exit(bool(result))
