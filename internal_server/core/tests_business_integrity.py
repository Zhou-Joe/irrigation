"""Cross-entry-point permissions, exact accounting and review regressions."""
import json
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings, RequestFactory
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from .models import (Worker, DepartmentUserProfile, InventoryCategory, InventoryTransaction,
    InventoryTransactionLine, WorkReport, WaterRequest, Zone, PurchaseOrder, PurchaseOrderLine, Project, Landmark)


class BusinessIntegrityTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('integrity-manager', is_staff=True)
        self.owner = User.objects.create_user('integrity-worker')
        self.other = User.objects.create_user('integrity-other')
        self.dept = User.objects.create_user('integrity-dept')
        self.worker = Worker.objects.create(user=self.owner, employee_id='INT-1', full_name='A Worker')
        self.worker_b = Worker.objects.create(user=self.other, employee_id='INT-2', full_name='Z Worker')
        DepartmentUserProfile.objects.create(user=self.dept, employee_id='INT-D', full_name='Dept')
        self.cat = InventoryCategory.objects.create(code='INT-C', name_zh='Valve', current_stock=100)
        self.zone = Zone.objects.create(code='INT-Z', name='Zone')
        self.today = timezone.localdate()
        self.client.force_login(self.admin)

    def txn(self, **kwargs):
        values = dict(worker=self.worker, operation='出库', entry_subtype='项目', consumption_mode='actual', confirm_status='pending', date=self.today)
        values.update(kwargs)
        txn = InventoryTransaction.objects.create(**values)
        InventoryTransactionLine.objects.create(transaction=txn, category=self.cat, quantity=5)
        return txn

    def test_patch_keeps_boundary_unless_explicitly_changed(self):
        points = [{'lat':31.1, 'lng':121.1}, {'lat':31.2, 'lng':121.1}, {'lat':31.2, 'lng':121.2}, {'lat':31.1, 'lng':121.1}]
        self.zone.boundary_points = points; self.zone.save()
        api = APIClient(); api.force_authenticate(self.admin)
        result = api.patch(f'/api/zones/{self.zone.pk}/', {'name':'Rename'}, format='json')
        self.assertEqual(result.status_code, 200)
        self.zone.refresh_from_db(); self.assertEqual(self.zone.boundary_points, points)

    def test_department_cannot_edit_workreport_or_delete_landmark(self):
        wr = WorkReport.objects.create(worker=self.worker, date=self.today, remark='Original')
        lm = Landmark.objects.create(name='Private Landmark')
        self.client.force_login(self.dept)
        response = self.client.post(reverse('core:workorder_tree_form_edit', args=[wr.pk]),
            {'date':str(self.today), 'entries':'[]', 'materials':'[]', 'remark':'Changed'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.post(reverse('core:landmark_delete', args=[lm.pk])).status_code, 403)
        wr.refresh_from_db(); self.assertEqual(wr.remark, 'Original')
        self.assertTrue(Landmark.objects.filter(pk=lm.pk).exists())

    def test_employee_cannot_edit_other_or_confirmed_inventory(self):
        txn = self.txn(confirm_status='confirmed')
        for user in (self.other, self.owner):
            self.client.force_login(user)
            response = self.client.post('/mobile/inventory/v2/', {'txn_id':txn.pk, 'operation':'出库',
                'entry_subtype':'项目', 'date':str(self.today), 'lines':json.dumps([{'category':self.cat.pk,'quantity':9}])},
                HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(response.status_code, 403)
        self.assertEqual(txn.lines.get().quantity, 5)

    def test_employee_cannot_void_foreign_estimate(self):
        txn = self.txn(consumption_mode='estimated')
        self.client.force_login(self.other)
        result = self.client.post(reverse('core:inventory_estimate_void', args=[txn.pk]))
        self.assertEqual(result.status_code, 409)
        self.assertTrue(InventoryTransaction.objects.filter(pk=txn.pk).exists())

    def test_disabled_user_token_is_rejected(self):
        from .authentication import TokenAuthentication
        from rest_framework.exceptions import AuthenticationFailed
        self.owner.is_active = False; self.owner.save()
        with self.assertRaises(AuthenticationFailed):
            TokenAuthentication().authenticate_credentials(str(self.worker.api_token))

    def test_dept_api_request_attribution_and_admin_context(self):
        api=APIClient(); api.force_authenticate(self.dept)
        response=api.post('/api/water-requests/', {'zones':[self.zone.pk], 'start_datetime':'2026-10-25T06:00:00+08:00',
            'end_datetime':'2026-10-25T18:00:00+08:00'}, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        wr=WaterRequest.objects.get(pk=response.data['id'])
        self.assertEqual(wr.submitter_user_id, self.dept.pk); self.assertEqual(wr.zone_id,self.zone.pk)
        self.assertIsNone(wr.submitter_id)
        wr.zone=None; wr.save()
        from .context_processors import notifications
        request=RequestFactory().get('/'); request.user=self.admin
        self.assertTrue(notifications(request))

    def test_api_owner_cannot_self_approve_or_forge_submitter(self):
        wr=WaterRequest.objects.create(submitter=self.worker, zone=self.zone, start_datetime=timezone.now(), end_datetime=timezone.now()+timedelta(hours=1))
        api=APIClient();api.force_authenticate(self.worker)
        response=api.patch(f'/api/water-requests/{wr.pk}/',{'status':'approved'},format='json')
        self.assertEqual(response.status_code,400)
        wr.refresh_from_db(); self.assertEqual(wr.status,'submitted')

    def test_bad_quantity_rolls_back_without_balance_drift(self):
        for bad in (1.5, -1, 'NaN', 'Infinity', 0, {}, True):
            response=self.client.post('/mobile/inventory/v2/', {'operation':'出库', 'date':str(self.today),
                'lines':json.dumps([{'category':self.cat.pk,'quantity':bad}])}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(response.status_code,400, str(bad))
        self.cat.refresh_from_db();self.assertEqual(self.cat.current_stock,100)
        self.assertFalse(InventoryTransaction.objects.exists())

    def test_project_and_po_use_only_confirmed_actual(self):
        from .workorder_tree_views import _project_budget_data
        project=Project.objects.create(name='Project')
        self.txn(related_project=project)
        self.assertEqual(_project_budget_data([project])[project.pk]['material_consumed'], [])
        po=PurchaseOrder.objects.create(order_number='INT-PO')
        PurchaseOrderLine.objects.create(purchase_order=po,category=self.cat,quantity=5)
        receipt=self.txn(operation='入库',entry_subtype='采购',purchase_order=po,confirm_status='removed')
        self.assertFalse(self.client.post(reverse('core:purchase_order_complete',args=[po.pk])).json()['success'])
        receipt.confirm_status='confirmed';receipt.save()
        self.assertTrue(self.client.post(reverse('core:purchase_order_complete',args=[po.pk])).json()['success'])
        self.client.post('/inventory/txn/unconfirm/',{'txn_ids':[receipt.pk]})
        po.refresh_from_db(); self.assertFalse(po.is_completed)

    def test_state_claim_prevents_stale_candidate_double_deduction(self):
        from .inventory_service import transition
        txn=self.txn()
        stale_a=InventoryTransaction.objects.get(pk=txn.pk);stale_b=InventoryTransaction.objects.get(pk=txn.pk)
        original=InventoryTransaction.objects.filter
        candidates=iter([[stale_a],[stale_b]])
        def scheduled(*args,**kwargs):
            if 'pk__in' in kwargs:return next(candidates)
            return original(*args,**kwargs)
        # Supply stale candidate selections directly at the service boundary;
        # its conditional claim still consults the real database.
        class Candidates(list):
            def filter(self,**kw):return self
        with patch.object(InventoryTransaction.objects,'filter',side_effect=lambda *a,**kw: Candidates(next(candidates)) if 'pk__in' in kw else original(*a,**kw)):
            self.assertEqual(transition([txn.pk],'confirm'),1)
            self.assertEqual(transition([txn.pk],'confirm'),0)
        self.cat.refresh_from_db(); self.assertEqual(self.cat.current_stock,95)

    def test_workreport_api_uses_current_relations(self):
        WorkReport.objects.create(worker=self.worker,date=self.today)
        response=self.client.get('/api/work-reports/')
        self.assertEqual(response.status_code,200)

    def test_reverse_time_is_rejected(self):
        self.client.force_login(self.dept)
        response=self.client.post('/mobile/water-request/v2/',{'zone_codes':json.dumps([self.zone.code]),
            'start_datetime':'2026-10-25T18:00','end_datetime':'2026-10-25T06:00'})
        self.assertEqual(response.status_code,400)
        self.assertFalse(WaterRequest.objects.exists())

    def test_no_role_navigation_dead_end(self):
        from .pwa import navigation
        request=RequestFactory().get('/app/');request.user=self.dept
        self.assertNotIn('inventory_management',{m['name'] for m in navigation(request)['pwa_modules']})

    def test_media_route_never_serves_ai_checkpoints(self):
        import config.urls
        route=next(p for p in config.urls.urlpatterns if str(p.pattern).startswith('^media/'))
        from django.conf import settings
        with tempfile.TemporaryDirectory(dir=settings.BASE_DIR) as media, patch.dict(route.default_args,document_root=media):
            Path(media,'ai_checkpoints.sqlite3').write_bytes(b'private fixture')
            self.assertEqual(self.client.get('/media/ai_checkpoints.sqlite3').status_code,404)

    def test_geometry_and_dxf_landmark_share_active_boundary(self):
        from .views import _recalculate_landmark_assignments
        from .models import ZoneLandmarkAssignment
        points=[{'lat':31.1,'lng':121.1},{'lat':31.2,'lng':121.1},{'lat':31.2,'lng':121.2},{'lat':31.1,'lng':121.1}]
        self.zone.dxf_boundary_points=points;self.zone.boundary_source='dxf';self.zone.save()
        lm=Landmark.objects.create(name='DXF',boundary_points=points)
        self.assertIn(self.zone.code,[z['c'] for z in self.client.get('/api/zone-geo/').json()])
        self.assertEqual(_recalculate_landmark_assignments(),1)
        self.assertTrue(ZoneLandmarkAssignment.objects.filter(zone=self.zone,landmark=lm).exists())
        with patch.object(ZoneLandmarkAssignment.objects,'bulk_create',side_effect=RuntimeError('fixture')):
            with self.assertRaises(RuntimeError):_recalculate_landmark_assignments()
        self.assertTrue(ZoneLandmarkAssignment.objects.filter(zone=self.zone,landmark=lm).exists())

    def test_people_sorted_pagination_never_loses_or_repeats(self):
        from .views import WORK_REPORTS_PAGE_SIZE
        WorkReport.objects.bulk_create([WorkReport(worker=self.worker,date=self.today) for _ in range(WORK_REPORTS_PAGE_SIZE)])
        last=WorkReport.objects.create(worker=self.worker_b,date=self.today)
        first=self.client.get('/work-reports/',{'sort':'worker','ajax':'1'}).json()
        for key,value in [('cursor',first['next_cursor']),('before_id',first['last_id'])]:
            second=self.client.get('/work-reports/',{'sort':'worker','ajax':'1',key:value}).json()
            self.assertEqual([r['id'] for r in second['reports']],[last.pk])
        self.assertEqual(self.client.get('/work-reports/',{'sort':'id','ajax':'1','cursor':first['next_cursor']}).status_code,400)

    def test_hidden_workreport_tabs_do_not_scan_remarks(self):
        with patch('core.views._group_zone_remarks',side_effect=AssertionError('hidden tab scanned')):
            self.assertEqual(self.client.get('/work-reports/').status_code,200)

    def test_catalog_api_and_settings_query_count_is_bounded(self):
        from .models import Patch,Region
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        from django.http import HttpResponse
        from .views import settings_page
        region=Region.objects.create(name='Scale')
        for i in range(12):Patch.objects.create(code=f'INTEGRITY-{i}',name='Scale',region=region)
        with CaptureQueriesContext(connection) as queries:self.client.get('/api/patches/')
        self.assertEqual(len([q for q in queries if 'FROM "core_region"' in q['sql']]),0)
        request=RequestFactory().get('/settings/');request.user=self.admin
        with patch('core.views.render',return_value=HttpResponse('fixture')),CaptureQueriesContext(connection) as queries:
            settings_page(request)
        self.assertEqual(len([q for q in queries if 'COUNT(*)' in q['sql'] and '"core_patch"."parent_id" =' in q['sql']]),0)

    def test_receipt_replays_once_and_rejects_changed_payload(self):
        import uuid
        key=str(uuid.uuid4())
        data={'operation':'出库','date':str(self.today),'lines':json.dumps([{'category':self.cat.pk,'quantity':5}])}
        headers={'HTTP_X_REQUESTED_WITH':'XMLHttpRequest','HTTP_X_SUBMISSION_KEY':key}
        first=self.client.post('/mobile/inventory/v2/',data,**headers)
        second=self.client.post('/mobile/inventory/v2/',data,**headers)
        self.assertTrue(first.json()['success']);self.assertEqual(second.headers['Idempotency-Replayed'],'true')
        self.assertEqual(InventoryTransaction.objects.count(),1)
        self.cat.refresh_from_db();self.assertEqual(self.cat.current_stock,95)
        data['lines']=json.dumps([{'category':self.cat.pk,'quantity':9}])
        self.assertEqual(self.client.post('/mobile/inventory/v2/',data,**headers).status_code,409)
        self.assertTrue(self.client.get(f'/api/submissions/{key}/').json()['found'])
        self.client.force_login(self.other)
        self.assertFalse(self.client.get(f'/api/submissions/{key}/').json()['found'])

    def test_receipt_validation_failure_can_retry_corrected_payload(self):
        import uuid
        key=str(uuid.uuid4())
        data={'operation':'出库','date':str(self.today),'lines':json.dumps([{'category':self.cat.pk,'quantity':1.5}])}
        headers={'HTTP_X_REQUESTED_WITH':'XMLHttpRequest','HTTP_X_SUBMISSION_KEY':key}
        self.assertEqual(self.client.post('/mobile/inventory/v2/',data,**headers).status_code,400)
        data['lines']=json.dumps([{'category':self.cat.pk,'quantity':1}])
        self.assertTrue(self.client.post('/mobile/inventory/v2/',data,**headers).json()['success'])

    def test_partial_mail_failure_and_repeated_slot_are_visible(self):
        from .models import EmailReportConfig,EmailDispatch
        from io import BytesIO,StringIO
        from django.core.management import call_command
        cfg=EmailReportConfig.objects.create(name='Mail',recipients='fixture@example.invalid',
            report_types=['zones','irrigation'],send_hour=timezone.localtime().hour)
        def attachments(*args,**kwargs):return [('fixture.xlsx',BytesIO(b'fixture'),'Zone'),(None,None,'FAILED:irrigation:fixture')]
        with patch('core.smtp_utils.is_smtp_configured',return_value=True),patch('core.management.commands.send_report_email._build_all_attachments',side_effect=attachments),\
             patch('core.smtp_utils.get_email_connection',return_value=None),patch('core.smtp_utils.resolve_from_email',return_value='fixture@example.invalid'),\
             patch('django.core.mail.EmailMessage.send',return_value=1) as send:
            call_command('send_report_email',stdout=StringIO());call_command('send_report_email',stdout=StringIO())
            self.assertEqual(send.call_count,1)
        cfg.refresh_from_db();self.assertTrue(cfg.last_status.startswith('partial_success'))
        dispatch=EmailDispatch.objects.get(config=cfg)
        self.assertEqual(dispatch.status,'partial_success');self.assertEqual(len(dispatch.details['failures']),1)

    def test_approval_profile_failure_rolls_back_user_and_request(self):
        from .registration_service import approve
        from .models import RegistrationRequest
        reg=RegistrationRequest.objects.create(username='new-integrity-user',full_name='New',phone='000',requested_role='field_worker',password='fixture')
        with patch.object(Worker.objects,'create',side_effect=RuntimeError('fixture')):
            with self.assertRaises(RuntimeError):approve(reg.pk,self.admin)
        self.assertFalse(User.objects.filter(username=reg.username).exists())
        reg.refresh_from_db();self.assertEqual(reg.status,'pending');self.assertIsNone(reg.processed_at)

    def test_receipt_and_inventory_tabs_are_bounded(self):
        for _ in range(34):self.txn()
        response=self.client.get('/inventory/manage/',{'tab':'ledger'})
        self.assertEqual(len(response.context['pending_txns']),30)
        self.assertEqual(response.context['pending_txns'].paginator.count,34)
        self.assertEqual(len(self.client.get('/inventory/manage/',{'tab':'ledger','pending_page':2}).context['pending_txns']),4)
        self.assertEqual(list(self.client.get('/inventory/manage/',{'tab':'tree'}).context['pending_txns']),[])

    def test_ai_conversations_and_artifacts_are_owner_scoped(self):
        from .models import AISettings,AIConversation
        from .ai_storage import workspace,artifact_url
        from django.conf import settings
        AISettings.objects.create(enabled=True,api_base_url='https://example.invalid',api_key='fixture',model_name='fixture')
        thread=f'u{self.admin.pk}-abcdef12'
        AIConversation.objects.create(id=thread,owner=self.admin)
        other_admin=User.objects.create_user('second-integrity-admin',is_staff=True)
        with tempfile.TemporaryDirectory(dir=settings.BASE_DIR) as private,override_settings(AI_PRIVATE_ROOT=private):
            (workspace(thread)/'result.csv').write_text('fixture',encoding='utf-8')
            response=self.client.get(artifact_url(thread,'result.csv'))
            self.assertEqual(response.status_code,200);response.close()
            self.client.force_login(other_admin)
            self.assertEqual(self.client.get(artifact_url(thread,'result.csv')).status_code,403)
            self.assertEqual(self.client.post('/api/ai/chat',json.dumps({'message':'fixture','thread_id':thread}),content_type='application/json').status_code,403)

    def test_python_execution_has_no_unsafe_fallback(self):
        from .ai_executor import execute
        from django.conf import settings
        with tempfile.TemporaryDirectory(dir=settings.BASE_DIR) as workspace,override_settings(AI_EXECUTOR_IMAGE=''),patch('core.ai_executor.subprocess.Popen') as launch:
            result=execute("print('fixture')",workspace)
            self.assertIn('error',result);launch.assert_not_called()

    def test_refreshed_ai_snapshot_uses_only_accepted_actual_project_consumption(self):
        import csv
        from .ai_agent import ensure_workspace
        from .models import InventoryPriceRecord
        from django.conf import settings
        project=Project.objects.create(name='Snapshot Project')
        accepted=self.txn(confirm_status='confirmed',related_project=project)
        self.txn(confirm_status='pending',related_project=project)
        self.txn(confirm_status='confirmed',consumption_mode='estimated',related_project=project)
        InventoryPriceRecord.objects.create(category=self.cat,date=self.today-timedelta(days=1),unit_price='2.50',is_current=True)
        InventoryPriceRecord.objects.create(category=self.cat,date=self.today,unit_price='9.99')
        with tempfile.TemporaryDirectory(dir=settings.BASE_DIR) as private,override_settings(AI_PRIVATE_ROOT=private):
            ws=Path(ensure_workspace(f'u{self.admin.pk}-abcdef12',refresh=True))
            def rows():
                with (ws/'project_consumption.csv').open(encoding='utf-8-sig',newline='') as source:return list(csv.DictReader(source))
            self.assertEqual(len(rows()),1);self.assertEqual(rows()[0]['数量'],'5');self.assertEqual(rows()[0]['单价'],'2.5')
            accepted.lines.update(quantity=7)
            ensure_workspace(f'u{self.admin.pk}-abcdef12',refresh=True)
            self.assertEqual(rows()[0]['数量'],'7')

    def test_current_runtime_matrix_uses_sql_sum_without_losing_values(self):
        from .models import Patch,MaxicomRuntime,MaxicomController
        from .irrigation_queries import runtime_buckets
        from .views import _build_ccu_matrix
        ccu=Patch.objects.create(code='INTEGRITY-CCU',name='CCU')
        st=Patch.objects.create(code='station-integrity',name='Station',parent=ccu,controller_number=9901,controller_channel=1)
        ctrl=MaxicomController.objects.create(mdb_index=9901,site=ccu,name='SAT 1-1',site_number=1,link_number=1,link_channel=1)
        MaxicomRuntime.objects.bulk_create([MaxicomRuntime(site=ccu,station=st,station_id_raw=1,timestamp='20261025100000',run_time=5) for _ in range(20)])
        buckets,metadata=runtime_buckets(MaxicomRuntime.objects.all())
        self.assertEqual(len(buckets[ccu.pk]),1)
        matrix=_build_ccu_matrix(ccu,buckets[ccu.pk],{9901:ctrl},set(),stations=metadata[ccu.pk])
        self.assertEqual(matrix['grand_total'],100)
