import uuid
from datetime import timedelta
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (BusinessArea, Membership, Team, Location, LocationGrant, AuditEvent,
                     LandscapingAsset as Asset, LandscapingSpecies as Species,
                     LandscapingWorkOrder as WorkOrder, LandscapingDelivery as Delivery)


@override_settings(MULTI_TEAM_ENABLED=True, PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class LandscapingWorkspaceTests(TestCase):
    def setUp(self):
        self.team = Team.objects.get(code='landscaping')
        self.user = User.objects.create_user('green-field', password='fixture-password')
        Membership.objects.create(user=self.user, team=self.team, role='field')
        self.client.force_login(self.user)

    def test_green_account_has_framework_and_shared_profile_and_feedback(self):
        response = self.client.get('/')
        self.assertContains(response, '植物与区域地图')
        self.assertContains(response, 'id="dashboardWorkspace"')
        self.assertEqual(response.context['business_choices'], [{'code':'landscaping','label':'绿化'}])
        self.assertEqual({module['name'] for module in response.context['pwa_modules']},
                         {'dashboard', 'green_assets', 'green_species', 'green_workorders', 'locations', 'profile','feedback'})
        self.assertNotContains(response, '地图总览')
        self.assertContains(self.client.get('/ops/profile/'), '绿化团队')
        self.assertEqual(self.client.get('/feedback/').status_code, 200)
        self.assertRedirects(self.client.get('/app/'), '/')

    def test_green_account_cannot_use_other_business_operations(self):
        for path in ('/api/zones-payload/', '/api/modal/workorder-data/', '/work-reports/',
                     '/ops/reports/', '/ops/plans/'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(self.client.post('/mobile/workorder/v2/', {}).status_code, 403)
        self.assertEqual(self.client.post('/ops/switch/', {'business':'irrigation'}).status_code, 403)

    def test_admin_can_switch_to_green_and_back_without_assuming_membership(self):
        business = BusinessArea.objects.create(code='irrigation', name='灌溉')
        Team.objects.create(business=business, code='irrigation', name='灌溉团队', legacy_irrigation_access=True)
        admin = User.objects.create_superuser('green-admin', '', 'fixture-password')
        self.client.force_login(admin)
        response = self.client.post('/ops/switch/', {'business':'landscaping'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertContains(self.client.get('/'), 'data-business="landscaping"')
        response = self.client.post('/ops/switch/', {'business':'irrigation'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/').context['business_selected'], 'irrigation')
        self.assertFalse(Membership.objects.filter(user=admin).exists())


@override_settings(MULTI_TEAM_ENABLED=True, PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class LandscapingRecordTests(TestCase):
    def setUp(self):
        self.team = Team.objects.get(code='landscaping')
        self.manager = User.objects.create_user('green-manager', password='fixture-password')
        self.field = User.objects.create_user('green-field', password='fixture-password')
        self.other_field = User.objects.create_user('green-other', password='fixture-password')
        self.viewer = User.objects.create_user('green-viewer', password='fixture-password')
        for user, role in [(self.manager,'manager'),(self.field,'field'),(self.other_field,'field'),(self.viewer,'viewer')]:
            Membership.objects.create(user=user, team=self.team, role=role)
        self.other_team = Team.objects.create(business=self.team.business, code='green-other-team', name='另一绿化团队')
        self.place = Location.objects.create(owner_team=self.team, name='绿化区域')
        self.hidden = Location.objects.create(owner_team=self.other_team, name='不应泄露的位置')
        self.species = Species.objects.create(team=self.team, code='SP-001', name='测试植物', special=True)
        self.asset = Asset.objects.create(team=self.team, code='TR-001', name='测试树木', location=self.place,
                                         latitude='31.145663', longitude='121.655407', measurement_method='rtk')
        self.asset.species.add(self.species)
        self.other_asset = Asset.objects.create(team=self.other_team, code='SECRET-1', name='其他团队树木')
        self.order = WorkOrder.objects.create(team=self.team, title='树木巡检', instructions='核查树干与根颈',
            scheduled_date=timezone.localdate(), assignee=self.field, created_by=self.manager, location=self.place)
        self.order.assets.add(self.asset)
        self.client.force_login(self.manager)

    def url(self, name, *args):
        return reverse('operations:green_' + name, args=args)

    def test_all_framework_pages_render_with_scoped_records(self):
        for name, args in [('assets',()),('species',()),('asset',(self.asset.pk,)),('asset_edit',(self.asset.pk,)),
                           ('species_edit',(self.species.pk,)),('workorders',()),('workorder',(self.order.pk,)),
                           ('workorder_new',()),('deliveries',()),('delivery_new',())]:
            with self.subTest(name=name):
                result = self.client.get(self.url(name,*args))
                self.assertEqual(result.status_code,200)
                self.assertNotContains(result, '不应泄露的位置')
                self.assertNotContains(result, 'SECRET-1')
        self.assertEqual(self.client.get(self.url('asset',self.other_asset.pk)).status_code,404)

    def test_map_has_only_owned_assets_and_granted_locations(self):
        grant = LocationGrant.objects.create(location=self.hidden, team=self.team)
        before = self.client.get(self.url('map_data')).json()
        self.assertEqual({a['code'] for a in before['assets']},{'TR-001'})
        self.assertEqual({p['name'] for p in before['locations']},{self.place.name,self.hidden.name})
        grant.delete()
        after = self.client.get(self.url('map_data')).json()
        self.assertEqual({p['name'] for p in after['locations']},{self.place.name})
        result=self.client.get(self.url('map_data')+'?special=1').json()
        self.assertEqual(len(result['assets']),1)
        self.assertContains(self.client.get('/'),'绿化总览')

    def test_field_can_read_master_data_but_cannot_write_or_accept_deliveries(self):
        self.client.force_login(self.field)
        for name in ('assets','species','workorders'):
            self.assertEqual(self.client.get(self.url(name)).status_code,200)
        for name in ('asset_new','species_new','delivery_new','deliveries'):
            self.assertEqual(self.client.get(self.url(name)).status_code,403)
            self.assertEqual(self.client.post(self.url(name),{}).status_code,403 if name!='deliveries' else 405)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(self.url('workorder_new')).status_code,403)

    def test_asset_validation_keeps_code_coordinates_and_references_consistent(self):
        data={'code':'TR-NEW','name':'新树木','kind':'tree','measurement_method':'unmeasured','risk':'unassessed'}
        result=self.client.post(self.url('asset_new'),{**data,'location':self.hidden.pk})
        self.assertEqual(result.status_code,200)
        self.assertFalse(Asset.objects.filter(code='TR-NEW').exists())
        result=self.client.post(self.url('asset_new'),{**data,'latitude':'31.14'})
        self.assertContains(result,'经纬度需要同时填写')
        result=self.client.post(self.url('asset_new'),{**data,'location':self.place.pk,'species':[self.species.pk]})
        self.assertEqual(result.status_code,302)
        obj=Asset.objects.get(code='TR-NEW')
        self.assertEqual(obj.team,self.team)
        self.assertEqual(obj.species.get(),self.species)
        self.assertEqual(self.client.post(self.url('asset_new'),data).status_code,200)
        self.assertEqual(Asset.objects.filter(code='TR-NEW').count(),1)

    def test_species_confirmed_requires_identity_and_duplicate_submission_replays(self):
        data={'code':'SP-NEW','name':'新植物','category':'flower','identification':'confirmed'}
        self.assertContains(self.client.post(self.url('species_new'),data),'确认辨识前请填写拉丁学名')
        data.update(scientific_name='Testus plantus',submission_key=str(uuid.uuid4()))
        self.assertEqual(self.client.post(self.url('species_new'),data).status_code,302)
        repeat=self.client.post(self.url('species_new'),data)
        self.assertEqual(repeat['Idempotency-Replayed'],'true')
        self.assertEqual(Species.objects.filter(code='SP-NEW').count(),1)

    def test_cross_team_relations_cannot_be_posted(self):
        result=self.client.post(self.url('workorder_new'),{'title':'越界','kind':'inspection','instructions':'检查',
            'scheduled_date':timezone.localdate(),'assets':[self.other_asset.pk],'assignee':self.field.pk})
        self.assertEqual(result.status_code,200)
        self.assertFalse(WorkOrder.objects.filter(title='越界').exists())

    def test_field_creates_own_order_and_weather_is_system_snapshot(self):
        from core.models import WeatherData
        WeatherData.objects.create(date=timezone.localdate(),latitude=31,longitude=121,
            hourly_data=[{'hour':timezone.localtime().hour,'temp':24,'code':3}])
        self.client.force_login(self.field)
        result=self.client.post(self.url('workorder_new'),{'title':'补植','kind':'planting','instructions':'更换地被',
            'scheduled_date':timezone.localdate(),'assets':[self.asset.pk],'assignee':self.other_field.pk,'weather':'伪造天气'})
        self.assertEqual(result.status_code,302)
        order=WorkOrder.objects.get(title='补植')
        self.assertEqual(order.assignee,self.field)
        self.assertEqual(order.created_by,self.field)
        self.assertEqual(order.weather,'阴天, 24°C')
        detail=self.client.get(self.url('workorder',order.pk))
        self.assertContains(detail,'zd-head-right')
        self.assertContains(detail,'24°C')

    def action(self, action, notes='', version=None):
        self.order.refresh_from_db()
        return self.client.post(self.url('workorder_action',self.order.pk),{'action':action,'notes':notes,
            'version':version if version is not None else self.order.updated_at.isoformat()})

    def test_maintenance_requires_execution_then_manager_review_and_audits_each_step(self):
        self.client.force_login(self.field)
        self.assertEqual(self.action('complete').status_code,403)
        self.assertEqual(self.action('start').status_code,302)
        self.order.refresh_from_db();self.assertEqual(self.order.status,'in_progress')
        self.action('submit')
        self.order.refresh_from_db();self.assertEqual(self.order.status,'in_progress')
        self.action('submit','已处理树干问题')
        self.order.refresh_from_db();self.assertEqual(self.order.status,'pending_review')
        self.assertEqual(self.action('complete').status_code,403)
        self.client.force_login(self.manager)
        self.action('return','需要补充检查')
        self.order.refresh_from_db();self.assertEqual(self.order.status,'in_progress')
        self.action('submit','已补充检查')
        self.action('complete','复核通过')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status,'completed')
        self.assertEqual(self.order.reviewed_by,self.manager)
        self.assertIsNotNone(self.order.completed_at)
        self.assertEqual(AuditEvent.objects.filter(action='green.workorder.complete').count(),1)
        self.assertContains(self.client.get(self.url('workorder',self.order.pk)),'复核通过')

    def test_stale_actions_and_other_field_cannot_change_order(self):
        self.client.force_login(self.other_field)
        self.assertEqual(self.client.get(self.url('workorder',self.order.pk)).status_code,404)
        self.assertEqual(self.action('start').status_code,404)
        self.client.force_login(self.field)
        self.action('start',version='outdated')
        self.order.refresh_from_db();self.assertEqual(self.order.status,'pending')

    def test_all_record_filter_includes_old_orders_and_personal_scope(self):
        WorkOrder.objects.filter(pk=self.order.pk).update(created_at=timezone.now()-timedelta(days=800))
        self.assertNotContains(self.client.get(self.url('workorders')),'核查树干与根颈')
        self.assertEqual(self.client.get(self.url('workorders')).context['records'].paginator.count,0)
        self.assertEqual(self.client.get(self.url('workorders')+'?period=all').context['records'].paginator.count,1)
        self.client.force_login(self.other_field)
        self.assertEqual(self.client.get(self.url('workorders')+'?period=all').context['records'].paginator.count,0)

    def test_delivery_acceptance_is_only_a_register_and_requires_evidence(self):
        data={'name':'首区样板','supplier':'测试供应商','kind':'trees','region':'试点区域','record_count':10,'status':'accepted'}
        self.assertContains(self.client.post(self.url('delivery_new'),data),'请记录验收依据')
        data['notes']='验收记录存放于甲方资料库，编号 QA-001。'
        self.assertEqual(self.client.post(self.url('delivery_new'),data).status_code,302)
        self.assertEqual(Delivery.objects.get().status,'accepted')
        self.assertEqual(Asset.objects.filter(team=self.team).count(),1)
        self.assertContains(self.client.get(self.url('deliveries')),'不会自动导入')

    def test_pest_account_cannot_access_green_endpoints_even_when_guessing_ids(self):
        pest=BusinessArea.objects.create(code='pest-control',name='植保')
        team=Team.objects.create(business=pest,code='pest-test-green',name='植保测试')
        user=User.objects.create_user('pest-green-boundary')
        Membership.objects.create(user=user,team=team,role='manager')
        self.client.force_login(user)
        for name,args in [('assets',()),('map_data',()),('asset',(self.asset.pk,)),('workorder',(self.order.pk,))]:
            self.assertEqual(self.client.get(self.url(name,*args)).status_code,403)
