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
class BusinessViewTests(TestCase):
    def setUp(self):
        fixtures.WorkspaceTests.setUp(self)
        self.attribution=Worker.objects.create(user=self.admin,employee_id='ADMIN-ATTRIBUTION',full_name='Platform admin')
        self.catalog,_=import_reference(Path(__file__).resolve().parents[2]/'PM管理_层级结构整理版.md',self.pest)
        self.client.force_login(self.admin)

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

    def test_admin_selects_only_business_and_keeps_real_account_permissions(self):
        before=list(Membership.objects.filter(user=self.admin).values())
        for code,team in (('irrigation',self.it),('pest-control',self.pt)):
            response=self.client.post('/ops/switch/',{'business':code})
            self.assertRedirects(response,'/',fetch_redirect_response=False)
            page=self.client.get('/')
            self.assertTrue(page.context['is_admin'])
            self.assertEqual(page.context['workspace_membership'].team_id,team.pk)
            self.assertEqual(page.context['business_choices'],[{'code':'irrigation','label':'灌溉'},{'code':'pest-control','label':'植保'}])
            self.assertContains(page,'name="business"')
            self.assertNotContains(page,'name="admin_view"')
            self.assertNotContains(page,'经理视图')
            self.assertNotContains(page,'一线视图')
            self.assertContains(page,'js/ai-chat.js')
            self.assertEqual(self.client.get('/admin/').status_code,200)
            self.assertEqual(self.client.get('/profile/').context['profile_data']['type'],'超级管理员')
            if code=='irrigation':self.assertTrue(self.client.get('/api/modal/workorder-data/').json()['can_create_project'])
        self.assertEqual(before,list(Membership.objects.filter(user=self.admin).values()))
        self.admin.refresh_from_db();self.assertTrue(self.admin.is_superuser and self.admin.is_staff)

    def test_old_role_preview_sessions_keep_business_but_restore_actual_admin_authority(self):
        keys=[]
        for role in ('field','manager'):
            session=self.client.session;session['operations_admin_view']={'team':self.pt.pk,'role':role};session.save()
            page=self.client.get('/')
            self.assertTrue(page.context['is_admin'])
            self.assertTrue(page.context['pest_mode'])
            self.assertContains(page,'id="mapLocationCreate"')
            keys.append(page.context['active_business_key'])
        self.assertEqual(keys[0],keys[1])
        self.client.post('/ops/switch/',{'business':'irrigation'})
        self.assertNotIn('operations_admin_view',self.client.session)
        self.assertNotEqual(keys[0],self.client.get('/').context['active_business_key'])

    def test_business_selection_cannot_grant_access_or_change_a_regular_users_role(self):
        self.client.force_login(self.field)
        page=self.client.get('/')
        self.assertEqual(page.context['business_choices'],[{'code':'pest-control','label':'植保'}])
        self.assertFalse(page.context['is_admin'])
        self.assertNotContains(page,'id="mapLocationCreate"')
        self.assertEqual(self.client.post('/ops/switch/',{'business':'irrigation'}).status_code,403)
        self.assertEqual(self.client.post('/ops/switch/',{'business':'pest-control','role':'manager'}).status_code,302)
        self.assertFalse(self.client.get('/').context['is_admin'])
        self.assertEqual(self.client.get('/ops/locations/new/').status_code,403)
        self.assertEqual(self.client.post('/ops/switch/',{'admin_view':f'{self.it.pk}:manager'}).status_code,400)

    def test_two_business_account_uses_its_existing_memberships_for_management_modules(self):
        pest=Membership.objects.create(user=self.im,team=self.pt,role='field')
        self.client.force_login(self.im)
        self.client.post('/ops/switch/',{'business':'pest-control'})
        page=self.client.get('/')
        self.assertFalse(page.context['is_admin'])
        self.assertNotIn('team',{m['name'] for m in page.context['pwa_modules']})
        self.assertEqual(self.client.post('/ops/locations/batch/',{'team':self.pt.pk,'rows':'Denied'}).status_code,403)
        self.client.post('/ops/switch/',{'business':'irrigation'})
        self.assertTrue(self.client.get('/').context['is_admin'])
        self.client.post('/ops/switch/',{'business':'pest-control'})
        pest.active=False;pest.save()
        self.assertEqual(self.client.get('/').status_code,403)
        self.assertEqual(self.client.get('/ops/locations/').status_code,403)

    def test_invalid_inactive_and_csrf_requests_do_not_change_selected_business(self):
        self.client.post('/ops/switch/',{'business':'irrigation'})
        for value in ('bad','manager','pest-control:field',''):
            self.assertEqual(self.client.post('/ops/switch/',{'business':value}).status_code,400)
            self.assertEqual(self.client.session['operations_business'],'irrigation')
        self.pt.active=False;self.pt.save()
        self.assertEqual(self.client.post('/ops/switch/',{'business':'pest-control'}).status_code,403)
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.admin)
        self.assertEqual(csrf.post('/ops/switch/',{'business':'pest-control'}).status_code,403)

    def test_personal_and_team_records_depend_on_real_account_not_view_options(self):
        for user in (self.admin,self.field):
            report=WorkReport.all_businesses.create(worker=Worker.objects.get(user=user),date=timezone.localdate(),business_team=self.pt,work_content='fixture')
            PestWorkData.objects.create(report=report,catalog=self.catalog)
        self.client.post('/ops/switch/',{'business':'pest-control'})
        self.assertEqual(len(self.client.get('/api/zones-payload/').json()['records']),2)
        self.client.force_login(self.field)
        records=self.client.get('/api/zones-payload/').json()['records']
        self.assertEqual(len(records),1)
        self.assertEqual(WorkReport.all_businesses.get(pk=records[0]['id']).worker.user_id,self.field.pk)

    @override_settings(MULTI_TEAM_ENABLED=False)
    def test_feature_off_ignores_old_preview_sessions(self):
        session=self.client.session;session['operations_admin_view']={'team':self.it.pk,'role':'field'};session.save()
        page=self.client.get('/')
        self.assertTrue(page.context['is_admin'])
        self.assertNotContains(page,'name="business"')
        self.assertNotContains(page,'id="sharedLocationToggle"')
        self.assertTrue(self.client.get('/api/modal/workorder-data/').json()['can_create_project'])

    def test_ajax_switch_returns_json_and_components_without_redirect(self):
        response=self.client.post('/ops/switch/',{'business':'pest-control'},HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json(),{'success':True,'business':'pest-control'})
        self.assertNotIn('Location',response)
        for component in ('id="appNavigation"','id="dashboardWorkspace"','id="dashboardScripts"','operations/workspace.js'):
            self.assertContains(self.client.get('/'),component)

    def test_ai_and_management_modules_follow_account_authority_in_both_businesses(self):
        self.client.post('/ops/switch/',{'business':'pest-control'})
        page=self.client.get('/')
        self.assertIn('team',{m['name'] for m in page.context['pwa_modules']})
        self.assertEqual(self.client.get('/api/ai/status').status_code,200)
        self.client.force_login(self.field)
        self.assertNotContains(self.client.get('/'),'js/ai-chat.js')
        self.assertEqual(self.client.get('/api/ai/status').status_code,403)

    def test_map_placement_saves_consecutive_pins_without_files_or_redirect(self):
        import uuid
        self.client.force_login(self.pm)
        page=self.client.get('/')
        self.assertContains(page,'id="mapLocationCreate"')
        self.assertNotContains(page,'id="fosBatchDialog"')
        self.assertNotContains(page,'type="file"')
        before=Location.objects.filter(owner_team=self.pt).count()
        ids=[]
        for index,kind in enumerate(('building','monitoring')):
            payload={'team':self.pt.pk,'rows':f'Point {index}\t\t{kind}\t\t31.1434567\t121.6581234\t',
                     'submission_key':str(uuid.uuid4())}
            response=self.client.post('/ops/locations/batch/',payload,HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(response.status_code,200,response.content)
            self.assertNotIn('Location',response)
            ids += response.json()['ids']
            self.assertEqual(self.client.post('/ops/locations/batch/',payload).status_code,200)
        self.assertEqual(Location.objects.filter(owner_team=self.pt).count(),before+2)
        for place in Location.objects.filter(pk__in=ids):
            self.assertEqual(place.map_display,'pin')
            self.assertEqual(str(place.latitude),'31.1434567')
            self.assertEqual(place.code,'')
        self.assertEqual({p['id'] for p in self.client.get('/api/zones-payload/').json()['locations']},set(ids))

    def test_irrigation_shared_layer_only_reads_granted_places_and_observes_revocation(self):
        from .models import LocationGrant
        shared=Location.objects.create(owner_team=self.pt,name='Shared visitor centre',kind='building',map_display='pin',latitude=31.14,longitude=121.65)
        Location.objects.create(owner_team=self.pt,name='Private pest location',kind='monitoring',latitude=31.15,longitude=121.66)
        self.client.force_login(self.im)
        self.assertContains(self.client.get('/'),'id="sharedLocationToggle"')
        self.assertEqual(self.client.get('/ops/locations.geojson?shared=1').json()['locations'],[])
        grant=LocationGrant.objects.create(location=shared,team=self.it,created_by=self.pm)
        response=self.client.get('/ops/locations.geojson?shared=1&team='+str(self.pt.pk))
        self.assertIn('no-store',response['Cache-Control'])
        places=response.json()['locations']
        self.assertEqual([p['id'] for p in places],[str(shared.pk)])
        self.assertEqual(places[0]['owner_team'],self.pt.name)
        self.assertEqual(places[0]['map_display'],'pin')
        self.assertEqual(places[0]['center'],{'lat':31.14,'lng':121.65})
        self.assertNotIn('remarks',places[0])
        grant.delete()
        self.assertEqual(self.client.get('/ops/locations.geojson?shared=1').json()['locations'],[])

    def test_platform_admin_with_no_memberships_can_select_business_without_creating_accounts(self):
        Membership.objects.filter(user=self.admin).delete()
        self.assertEqual(self.client.get('/ops/locations.geojson?shared=1').status_code,200)
        self.assertEqual(self.client.post('/ops/switch/',{'business':'pest-control'}).status_code,302)
        self.assertTrue(self.client.get('/').context['is_admin'])
        self.assertFalse(Membership.objects.filter(user=self.admin).exists())
