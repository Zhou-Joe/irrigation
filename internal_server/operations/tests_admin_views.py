from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, Client, override_settings
from django.utils import timezone

from core.models import Worker, ManagerProfile, WorkReport
from core.role_utils import get_user_role
from . import tests as fixtures
from .catalog_import import import_reference
from .models import Membership, Location, ReferenceCatalog, PestWorkData


@override_settings(MULTI_TEAM_ENABLED=True)
class AdminRoleViewTests(TestCase):
    def setUp(self):
        fixtures.WorkspaceTests.setUp(self)
        self.attribution=Worker.objects.create(user=self.admin,employee_id='ADMIN-ATTRIBUTION',full_name='Platform admin')
        self.catalog,_=import_reference(Path(__file__).resolve().parents[2]/'PM管理_层级结构整理版.md',self.pest)
        self.client.force_login(self.admin)

    def switch(self,team,role):
        return self.client.post('/ops/switch/',{'admin_view':f'{team.pk}:{role}'})

    def test_attribution_worker_does_not_classify_superuser_as_field_staff(self):
        response=self.client.get('/profile/')
        self.assertEqual(response.context['profile_data']['type'],'超级管理员')
        self.assertTrue(response.context['profile_data']['is_super_admin'])
        self.assertEqual(response.context['profile_type'],'worker')
        rows=self.client.get('/user-management/').context['users_list']
        row=next(item for item in rows if item['user_id']==self.admin.pk)
        self.assertEqual(row['role'],'super_admin')
        self.assertEqual(row['role_display'],'超级管理员')
        self.assertFalse(ManagerProfile.objects.filter(user=self.admin).exists())
        self.assertTrue(Worker.objects.filter(pk=self.attribution.pk).exists())

    def test_superuser_can_view_all_four_roles_without_changing_identity_or_memberships(self):
        before=list(Membership.objects.filter(user=self.admin).values('id','team_id','role','active'))
        for team,pest in ((self.it,False),(self.pt,True)):
            for role in ('manager','field'):
                with self.subTest(team=team.code,role=role):
                    self.assertRedirects(self.switch(team,role),'/',fetch_redirect_response=False)
                    response=self.client.get('/')
                    self.assertEqual(response.status_code,200)
                    self.assertEqual(response.context['pest_mode'],pest)
                    self.assertEqual(response.context['is_admin'],role=='manager')
                    self.assertEqual(response.context['is_field_worker'],role=='field')
                    self.assertTrue(response.context['admin_role_preview'])
                    self.assertContains(response,'管理员角色视图')
                    self.assertNotContains(response,'js/ai-chat.js')
                    self.assertEqual(response.context['workspace_membership'].team_id,team.pk)
                    self.assertIsNone(response.context['workspace_membership'].pk)
                    data=self.client.get('/api/modal/workorder-data/').json()
                    if not pest:self.assertEqual(data['can_create_project'],role=='manager')
                    self.assertEqual(self.client.get('/admin/').status_code,200)
                    self.assertEqual(self.client.get('/profile/').context['profile_data']['type'],'超级管理员')
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_superuser and self.admin.is_staff)
        self.assertEqual(get_user_role(self.admin),'super_admin')
        self.assertEqual(before,list(Membership.objects.filter(user=self.admin).values('id','team_id','role','active')))

    def test_view_identity_changes_for_pwa_and_exit_restores_full_admin_view(self):
        self.switch(self.pt,'field');field=self.client.get('/')
        self.switch(self.pt,'manager');manager=self.client.get('/')
        self.assertNotEqual(field.context['active_business_key'],manager.context['active_business_key'])
        response=self.client.post('/ops/switch/',{'admin_view':'admin'})
        self.assertRedirects(response,'/',fetch_redirect_response=False)
        self.assertNotIn('operations_admin_view',self.client.session)
        response=self.client.get('/')
        self.assertFalse(response.context['admin_role_preview'])
        self.assertTrue(response.context['is_admin'])
        self.assertContains(response,'js/ai-chat.js')
        self.assertContains(response,'平台管理员')

    def test_non_superusers_cannot_request_or_forge_admin_role_views(self):
        for user in (self.pm,self.field,self.im):
            self.client.force_login(user)
            self.assertEqual(self.client.post('/ops/switch/',{'admin_view':f'{self.it.pk}:manager'}).status_code,403)
            session=self.client.session;session['operations_admin_view']={'team':self.it.pk,'role':'manager'};session.save()
            response=self.client.get('/')
            self.assertNotContains(response,'name="admin_view"')
            self.assertFalse(response.context['admin_role_preview'])
            self.assertEqual(response.context['pest_mode'],user!=self.im)

    def test_invalid_inactive_and_csrf_requests_leave_the_selected_view_intact(self):
        self.switch(self.it,'field')
        expected=dict(self.client.session['operations_admin_view'])
        for value in ('bad','x:field',f'{self.pt.pk}:super_admin',f'{self.pt.pk}:field:extra'):
            self.assertEqual(self.client.post('/ops/switch/',{'admin_view':value}).status_code,400)
            self.assertEqual(self.client.session['operations_admin_view'],expected)
        self.pt.active=False;self.pt.save()
        self.assertEqual(self.switch(self.pt,'manager').status_code,404)
        self.assertEqual(self.client.session['operations_admin_view'],expected)
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.admin)
        self.assertEqual(csrf.post('/ops/switch/',{'admin_view':f'{self.it.pk}:field'}).status_code,403)

    def test_pest_field_view_uses_personal_records_and_manager_view_uses_team_records(self):
        for user in (self.admin,self.field):
            worker=Worker.objects.get(user=user)
            report=WorkReport.all_businesses.create(worker=worker,date=timezone.localdate(),business_team=self.pt,work_content='view fixture')
            PestWorkData.objects.create(report=report,catalog=self.catalog)
        self.switch(self.pt,'field')
        data=self.client.get('/api/zones-payload/').json()
        self.assertEqual(len(data['records']),1)
        report=WorkReport.all_businesses.get(pk=data['records'][0]['id'])
        self.assertEqual(report.worker.user_id,self.admin.pk)
        self.switch(self.pt,'manager')
        self.assertEqual(len(self.client.get('/api/zones-payload/').json()['records']),2)

    @override_settings(MULTI_TEAM_ENABLED=False)
    def test_feature_off_ignores_stale_preview_sessions(self):
        session=self.client.session;session['operations_admin_view']={'team':self.it.pk,'role':'field'};session.save()
        response=self.client.get('/')
        self.assertTrue(response.context['is_admin'])
        self.assertNotContains(response,'name="admin_view"')
        self.assertTrue(self.client.get('/api/modal/workorder-data/').json()['can_create_project'])

    def test_irrigation_field_view_limits_pm_to_own_crew_without_changing_normal_admin_scope(self):
        from core.models import JobPlanTemplate,MaintenancePlan,GeneratedWorkOrder
        job=JobPlanTemplate.objects.create(name='Admin preview PM')
        for index,worker in enumerate((self.attribution,Worker.objects.get(user=self.field))):
            plan=MaintenancePlan.objects.create(pm_number=f'PREVIEW-{index}',job_plan=job,start_date=timezone.localdate())
            GeneratedWorkOrder.objects.create(plan=plan,worker=worker,scheduled_date=timezone.localdate())
        self.switch(self.it,'field')
        self.assertEqual(self.client.get('/').context['pm_tasks_total'],1)
        self.assertEqual(self.client.get('/work-reports/pm-tasks/').json()['total'],1)
        self.switch(self.it,'manager')
        self.assertEqual(self.client.get('/').context['pm_tasks_total'],2)
        self.assertEqual(self.client.get('/work-reports/pm-tasks/').json()['total'],2)

    def test_ajax_view_switch_returns_state_without_page_redirect(self):
        response=self.client.post('/ops/switch/',{'admin_view':f'{self.pt.pk}:field'},HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(response.json()['business'],'pest-control')
        self.assertNotIn('Location',response)
        page=self.client.get('/')
        for component in ('id="appNavigation"','id="dashboardWorkspace"','id="dashboardScripts"','operations/workspace.js','operations/map-actions.js'):
            self.assertContains(page,component)
