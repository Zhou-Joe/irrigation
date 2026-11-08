import json
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings, Client

from core.models import Zone, Worker, ManagerProfile
from .models import BusinessArea, Team, Membership, Location, LocationGrant, AuditEvent
from .catalog_import import parse_outline, import_reference


@override_settings(MULTI_TEAM_ENABLED=True)
class WorkspaceTests(TestCase):
    def setUp(self):
        self.irrigation = BusinessArea.objects.create(code='irrigation', name='灌溉')
        self.pest = BusinessArea.objects.create(code='pest-control', name='植保')
        self.it = Team.objects.create(business=self.irrigation, code='irrigation', name='灌溉团队', legacy_irrigation_access=True)
        self.pt = Team.objects.create(business=self.pest, code='pest', name='植保团队')
        self.im = get_user_model().objects.create_user('irrigation-manager', password='test-only')
        self.pm = get_user_model().objects.create_user('pest-manager', password='test-only')
        self.field = get_user_model().objects.create_user('pest-field', password='test-only')
        self.admin = get_user_model().objects.create_superuser('platform', '', 'test-only')
        # Legacy global manager flags are deliberately present on the pest manager.
        ManagerProfile.objects.create(user=self.im, employee_id='IM', full_name='Irrigation')
        ManagerProfile.objects.create(user=self.pm, employee_id='PM', full_name='Pest')
        Worker.objects.create(user=self.field, employee_id='PF', full_name='Field')
        self.imm = Membership.objects.create(user=self.im, team=self.it, role='manager')
        self.pmm = Membership.objects.create(user=self.pm, team=self.pt, role='manager')
        self.fm = Membership.objects.create(user=self.field, team=self.pt, role='field')
        Membership.objects.create(user=self.admin, team=self.it, role='manager')
        self.zone = Zone.objects.create(code='6-7-28-pilot', name='Shared bed', remarks='private-irrigation-note',
            boundary_points=[[{'lat':31, 'lng':121}, {'lat':31.01, 'lng':121}, {'lat':31, 'lng':121.01}]],
            dxf_boundary_points=[[{'lat':32, 'lng':122}, {'lat':32.01, 'lng':122}, {'lat':32, 'lng':122.01}]],
            boundary_source='dxf', dxf_boundary_source='source.dxf')
        self.shared = Location.objects.create(owner_team=self.it, name='Shared bed', code='6-7-28-pilot', legacy_zone=self.zone)
        self.private = Location.objects.create(owner_team=self.it, name='Private building', code='PRIVATE')
        self.client.force_login(self.pm)

    def test_new_manager_cannot_read_legacy_pages_apis_ai_exports_or_media(self):
        for path in ['/api/zones-payload/', f'/zone/{self.zone.pk}/detail/', '/irrigation/',
                     '/user-management/', '/admin/', '/media/workreport/1/photo.jpg', '/ai/status/', '/stats/excel/']:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 403)
        self.assertRedirects(self.client.get('/'), '/ops/', fetch_redirect_response=False)

    def test_token_also_cannot_bypass_legacy_gate(self):
        token = self.pm.manager_profile.api_token
        client = Client()
        self.assertEqual(client.get('/api/zones-payload/', HTTP_AUTHORIZATION='Token '+str(token)).status_code, 403)

    def test_membership_does_not_leak_irrigation_status_in_shell(self):
        response = self.client.get('/ops/')
        self.assertContains(response, '植保团队')
        self.assertNotContains(response, 'private-irrigation-note')
        self.assertNotContains(response, 'navNotifBtn')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(self.client.get('/ops').status_code, 301)

    def test_only_explicit_place_sharing_exposes_live_geometry_not_work_data(self):
        self.assertEqual(self.client.get('/ops/locations.geojson').json()['locations'], [])
        self.assertEqual(self.client.get(f'/ops/locations/{self.shared.pk}/').status_code, 404)
        LocationGrant.objects.create(location=self.shared, team=self.pt, created_by=self.im)
        data = self.client.get('/ops/locations.geojson').json()['locations']
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['boundary'], self.zone.dxf_boundary_points)
        self.assertNotIn('private-irrigation-note', json.dumps(data))
        self.assertEqual(set(data[0]), {'id','name','code','kind','boundary','latitude','longitude','source'})
        self.zone.boundary_source = 'manual'
        self.zone.save()
        self.assertEqual(self.client.get('/ops/locations.geojson').json()['locations'][0]['boundary'], self.zone.boundary_points)
        LocationGrant.objects.all().delete()
        self.assertEqual(self.client.get(f'/ops/locations/{self.shared.pk}/').status_code, 404)

    def test_recipient_cannot_edit_regrant_or_import_irrigation_even_as_manager(self):
        LocationGrant.objects.create(location=self.shared, team=self.pt)
        self.assertEqual(self.client.post(f'/ops/locations/{self.shared.pk}/edit/', {'name':'Wrong'}).status_code, 404)
        self.assertEqual(self.client.post(f'/ops/locations/{self.shared.pk}/sharing/', {'team':self.pt.pk,'action':'grant'}).status_code, 404)
        self.assertEqual(self.client.post('/ops/locations/link-irrigation/', {'zone':self.zone.pk}).status_code, 403)
        self.shared.refresh_from_db()
        self.assertEqual(self.shared.name, 'Shared bed')

    def test_native_building_no_controller_code_and_scoped_parent(self):
        response = self.client.post('/ops/locations/new/', {'name':'Building A', 'kind':'building', 'code':'BLDG-A',
                                                         'latitude':'31.1234567','longitude':'121.2345678'})
        self.assertEqual(response.status_code, 302)
        building = Location.objects.get(name='Building A')
        self.assertEqual(building.owner_team_id, self.pt.pk)
        self.assertIsNone(building.legacy_zone_id)
        self.assertEqual(str(building.latitude), '31.1234567')
        self.assertEqual(self.client.post('/ops/locations/new/', {'name':'Room', 'kind':'room','parent':str(self.private.pk)}).status_code, 200)
        self.assertFalse(Location.objects.filter(name='Room').exists())
        self.assertEqual(self.client.post('/ops/locations/new/', {'name':'No coords','kind':'room','code':''}).status_code, 302)
        self.assertEqual(Zone.objects.count(), 1)

    def test_invalid_coordinates_cycles_duplicate_codes_and_forged_owner_rejected(self):
        for extra in ({'latitude':'91','longitude':'121'}, {'latitude':'31'}, {'latitude':'NaN','longitude':'121'}):
            response = self.client.post('/ops/locations/new/', {'name':'Invalid','kind':'building', **extra})
            self.assertEqual(response.status_code, 200)
        self.assertFalse(Location.objects.filter(name='Invalid').exists())
        parent = Location.objects.create(owner_team=self.pt, name='Parent', code='A')
        child = Location.objects.create(owner_team=self.pt, name='Child', parent=parent)
        self.client.post(f'/ops/locations/{parent.pk}/edit/', {'name':'Parent','kind':'building','parent':str(child.pk)})
        parent.refresh_from_db()
        self.assertIsNone(parent.parent_id)
        self.client.post('/ops/locations/new/', {'name':'Duplicate','kind':'building','code':'A'})
        self.assertFalse(Location.objects.filter(name='Duplicate').exists())
        self.client.post('/ops/locations/new/', {'name':'Forged owner','kind':'building','owner_team':self.it.pk})
        self.assertEqual(Location.objects.get(name='Forged owner').owner_team_id, self.pt.pk)

    def test_team_manager_cannot_promote_self_or_other_team(self):
        response = self.client.post('/ops/team/', {'username':self.field.username,'role':'manager'})
        self.assertContains(response, '经理角色由平台管理员授予')
        self.fm.refresh_from_db();self.assertEqual(self.fm.role,'field')
        self.assertEqual(self.client.post('/ops/team/', {'team':self.it.pk,'username':self.im.username,'role':'field'}).status_code,403)
        self.assertEqual(self.client.get('/ops/team/?team='+str(self.it.pk)).status_code,403)
        self.client.post('/ops/team/', {'username':self.pm.username,'role':'field'})
        self.pmm.refresh_from_db();self.assertEqual(self.pmm.role,'manager')

    def test_disable_and_account_disable_take_effect_without_relogin(self):
        self.client.force_login(self.field)
        self.assertEqual(self.client.get('/ops/locations/').status_code,200)
        self.fm.active=False;self.fm.save()
        self.assertEqual(self.client.get('/ops/locations/').status_code,403)
        self.fm.active=True;self.fm.save()
        self.field.is_active=False;self.field.save()
        self.assertEqual(self.client.get('/ops/locations/').status_code,302)

    def test_field_cannot_manage_and_csrf_required(self):
        self.client.force_login(self.field)
        for path in ['/ops/team/','/ops/locations/new/']:
            self.assertEqual(self.client.get(path).status_code,403)
        csrf = Client(enforce_csrf_checks=True);csrf.force_login(self.pm)
        self.assertEqual(csrf.post('/ops/locations/new/', {'name':'CSRF','kind':'room'}).status_code,403)

    def test_multi_role_switch_validates_membership_owner_and_revocation(self):
        second = Membership.objects.create(user=self.pm,team=self.it,role='viewer')
        self.assertEqual(self.client.post('/ops/switch/',{'membership':self.imm.pk}).status_code,404)
        self.assertEqual(self.client.post('/ops/switch/',{'membership':'bad'}).status_code,404)
        self.assertEqual(self.client.post('/ops/switch/',{'membership':second.pk}).status_code,302)
        self.assertContains(self.client.get('/ops/'), '只读成员')
        self.assertEqual(self.client.get('/ops/team/').status_code,403)
        # Legacy global ManagerProfile cannot turn a viewer membership into manager access.
        self.assertEqual(self.client.get('/api/zones-payload/').status_code,403)
        second.active=False;second.save()
        self.assertContains(self.client.get('/ops/'), '选择团队身份')
        self.assertEqual(self.client.get('/ops/locations/').status_code,403)

    def test_matching_legacy_manager_retains_irrigation_api(self):
        self.client.force_login(self.im)
        self.assertEqual(self.client.get('/api/zones-payload/').status_code,200)
        response=self.client.post('/ops/locations/link-irrigation/',{'zone':self.zone.pk})
        self.assertEqual(response.status_code,302)
        self.assertEqual(Location.objects.filter(legacy_zone=self.zone).count(),1)
        self.client.post(f'/ops/locations/{self.shared.pk}/sharing/', {'team':self.pt.pk,'action':'grant'})
        self.assertTrue(LocationGrant.objects.filter(location=self.shared,team=self.pt).exists())
        self.assertTrue(AuditEvent.objects.filter(action='location.grant').exists())

    def test_platform_admin_creates_account_without_global_manager_or_staff(self):
        self.client.force_login(self.admin)
        response=self.client.post('/ops/team/', {'team':self.pt.pk,'username':'new-pest-manager',
            'role':'manager','new_password':'Local-only-strong-test!2026'})
        self.assertEqual(response.status_code,302,response.content)
        user=get_user_model().objects.get(username='new-pest-manager')
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(ManagerProfile.objects.filter(user=user).exists())
        self.assertEqual(Membership.objects.get(user=user).team_id,self.pt.pk)
        self.client.force_login(user)
        self.assertEqual(self.client.get('/ops/team/').status_code,200)
        self.assertEqual(self.client.get('/api/zones-payload/').status_code,403)

    def test_link_code_collision_is_reported_without_partial_link_or_zone_change(self):
        another=Zone.objects.create(code='NATIVE-COLLISION',name='Source')
        Location.objects.create(owner_team=self.it,code=another.code,name='Different native place')
        self.client.force_login(self.im)
        response=self.client.post('/ops/locations/link-irrigation/',{'zone':another.pk})
        self.assertRedirects(response,'/ops/locations/link-irrigation/')
        self.assertFalse(Location.objects.filter(legacy_zone=another).exists())
        another.refresh_from_db();self.assertEqual(another.name,'Source')

    def test_scope_ignores_posted_business_and_hides_unshared_parent_name(self):
        own=Location.objects.create(owner_team=self.pt,name='Own room',parent=self.private)
        response=self.client.get(f'/ops/locations/{own.pk}/')
        self.assertNotContains(response,'Private building')
        self.client.post('/ops/locations/new/',{'name':'Scoped location','kind':'room',
            'business':self.irrigation.pk,'team':self.it.pk})
        self.assertEqual(Location.objects.get(name='Scoped location').owner_team_id,self.pt.pk)

    def test_locations_escape_labels_and_reference_is_business_scoped(self):
        from .models import ReferenceCatalog,ReferenceNode
        catalog=ReferenceCatalog.objects.create(business=self.pest,name='Pest',version='fixture',source_name='fixture.md')
        ReferenceNode.objects.create(catalog=catalog,label='<img src=x onerror=alert(1)>',kind='node',source_line=1,order=0)
        response=self.client.get('/ops/catalog/')
        self.assertContains(response,'&lt;img')
        self.assertNotContains(response,'<img src=x')
        self.client.force_login(self.im)
        self.assertNotContains(self.client.get('/ops/catalog/'),'&lt;img')

    def test_common_login_and_pwa_shell_are_available_without_irrigation_access(self):
        anonymous=Client()
        self.assertContains(anonymous.get('/login/'),'FOS 现场作业')
        self.assertNotContains(anonymous.get('/login/'),'申请加入')
        self.assertEqual(self.client.get('/manifest.webmanifest').json()['start_url'],'/ops/')
        self.assertEqual(self.client.get('/service-worker.js').status_code,200)
        self.assertEqual(self.client.get('/offline/').status_code,200)
        self.assertRedirects(self.client.get('/app/'),'/ops/',fetch_redirect_response=False)

    def test_bootstrap_is_idempotent_and_never_reactivates_or_grants_new_team_legacy_access(self):
        self.imm.active=False;self.imm.save()
        call_command('bootstrap_operations',assign_legacy=True,verbosity=0)
        call_command('bootstrap_operations',assign_legacy=True,verbosity=0)
        self.imm.refresh_from_db();self.assertFalse(self.imm.active)
        self.assertFalse(Membership.objects.filter(user=self.pm,team=self.it).exists())

    @override_settings(MULTI_TEAM_ENABLED=False)
    def test_feature_off_hides_new_routes_and_keeps_legacy_behavior(self):
        self.assertEqual(self.client.get('/ops/').status_code,404)
        self.assertEqual(self.client.get('/api/zones-payload/').status_code,200)


class CatalogTests(TestCase):
    def test_import_reference_keeps_paths_notes_repeated_names_and_is_idempotent(self):
        source=Path(__file__).resolve().parents[2]/'PM管理_层级结构整理版.md'
        parsed=parse_outline(source.read_text(encoding='utf-8'))
        self.assertEqual(sum(n['parent_index'] is None for n in parsed),7)
        self.assertEqual(sum(n['kind']=='note' for n in parsed),7)
        self.assertEqual(len(parsed),215)
        self.assertGreater(sum(n['label']=='人工处理' for n in parsed),1)
        business=BusinessArea.objects.create(code='pest-control',name='Pest')
        catalog,created=import_reference(source,business)
        self.assertTrue(created)
        self.assertEqual(catalog.nodes.count(),len(parsed))
        again,created=import_reference(source,business)
        self.assertFalse(created);self.assertEqual(again.pk,catalog.pk)
        note=catalog.nodes.filter(label='报封堵工单',kind='note').get()
        self.assertEqual(note.parent.label,'人工处理')

    def test_bad_tree_rejected_before_any_catalog_write(self):
        business=BusinessArea.objects.create(code='pest-control',name='Pest')
        from django.conf import settings
        with tempfile.TemporaryDirectory(dir=settings.BASE_DIR) as directory:
            path=Path(directory)/'bad.md';path.write_text('## 完整层级目录\n  - 没有父节点\n',encoding='utf-8')
            with self.assertRaises(ValueError):import_reference(path,business)
        self.assertEqual(business.referencecatalog_set.count(),0)
