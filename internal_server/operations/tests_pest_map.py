import uuid
import json
import re
from pathlib import Path
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import WorkReport
from . import tests as fixtures
from .models import Membership, Team, Location, LocationGrant, ReferenceCatalog, PestWorkData
from .catalog_import import import_reference


@override_settings(MULTI_TEAM_ENABLED=True)
class PestMapWorkflowTests(TestCase):
    def setUp(self):
        fixtures.WorkspaceTests.setUp(self)
        LocationGrant.objects.create(location=self.shared,team=self.pt)
        self.building=Location.objects.create(owner_team=self.pt,name='Building A',code='BLDG-A',kind='building',latitude=31,longitude=121)
        self.catalog,_=import_reference(Path(__file__).resolve().parents[2]/'PM管理_层级结构整理版.md',self.pest)
        self.leaf=self.catalog.nodes.filter(label='报封堵工单',kind='note').get()

    def payload(self, **extra):
        return {'team':str(self.pt.pk),'catalog':str(self.catalog.pk),'nodes':[str(self.leaf.pk)],
                'locations':[str(self.building.pk),str(self.shared.pk)],'date':timezone.localdate().isoformat(),
                'team_size':'2','remark':'Local pest work','submission_key':str(uuid.uuid4()),**extra}

    def test_both_field_and_manager_land_on_the_existing_map_and_open_real_hierarchy(self):
        for user in (self.pm,self.field):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                response=self.client.get('/')
                self.assertEqual(response.status_code,200)
                self.assertContains(response,'id="map"')
                self.assertContains(response,'operations/pest-map.js')
                self.assertContains(response,'创建工单')
                self.assertNotContains(response,'工作参考目录')
                self.assertNotContains(response,'团队工作台')
                self.assertNotContains(response,'js/dashboard-modal.js')
                data=self.client.get('/api/modal/workorder-data/').json()
                self.assertEqual(data['business'],'pest-control')
                tree=json.loads(re.search(r'<script id="pest-work-tree" type="application/json">(.*?)</script>',data['form_html'],re.S)[1])
                serialized_tree=json.dumps(tree,ensure_ascii=False)
                for label in ('病媒昆虫','蚊类控制','蜜蜂','白蚁监测','报封堵工单'):
                    self.assertIn(label,serialized_tree)
                self.assertIn('pestWorkorderForm',data['form_html'])
                for component in ('v2-chip-group','pestCategoryChips','pestPlaceChips','pestWorkLevels','work_start_time','third_party_count'):
                    self.assertIn(component,data['form_html'])
                for replaced_format in ('<details','type="checkbox"',' multiple','<fieldset'):
                    self.assertNotIn(replaced_format,data['form_html'])

    def test_same_map_endpoint_is_business_scoped_and_irrigation_keeps_old_layers(self):
        data=self.client.get('/api/zones-payload/').json()
        self.assertEqual({p['id'] for p in data['locations']},{str(self.shared.pk),str(self.building.pk)})
        self.assertNotIn('private-irrigation-note',str(data))
        self.client.force_login(self.im)
        response=self.client.get('/')
        self.assertContains(response,'js/map.js')
        self.assertNotContains(response,'operations/pest-map.js')
        self.assertNotContains(response,'operations/workorder-chips.js')
        self.assertNotContains(response,'operations/pest-map.css')
        self.assertNotContains(response,'operations/map-markers.js')
        self.assertIsInstance(self.client.get('/api/zones-payload/').json(),list)
        self.assertEqual(self.client.get('/app/').status_code,200)

    def test_only_new_business_workbench_entry_redirects_to_map(self):
        self.assertRedirects(self.client.get('/app/'),'/',fetch_redirect_response=False)

    def test_submission_saves_full_path_and_real_work_record_without_irrigation_leak(self):
        response=self.client.post('/mobile/workorder/v2/',self.payload())
        self.assertEqual(response.status_code,200,response.content)
        self.assertTrue(response.json()['success'])
        report=WorkReport.all_businesses.get(pk=response.json()['report_id'])
        self.assertEqual(report.business_team_id,self.pt.pk)
        self.assertEqual(report.worker.user_id,self.pm.pk)
        self.assertTrue(report.display_number.startswith('PPC-'))
        self.assertEqual(report.pest_data.selections[0]['path'],['传粉昆虫','蜜蜂','自然筑巢','建筑','人工处理','报封堵工单'])
        self.assertEqual(report.pest_data.locations.count(),2)
        self.assertEqual(report.zones.count(),0)
        self.assertEqual(WorkReport.objects.count(),0)
        self.assertContains(self.client.get('/work-reports/'),report.display_number)
        self.assertContains(self.client.get(f'/work-reports/{report.pk}/'),'报封堵工单')
        self.client.force_login(self.im)
        self.assertNotContains(self.client.get('/work-reports/'),report.display_number)
        self.assertEqual(self.client.get(f'/work-reports/{report.pk}/').status_code,404)

    def test_field_sees_own_records_manager_sees_team_but_not_other_team(self):
        self.client.force_login(self.field)
        own=self.client.post('/mobile/workorder/v2/',self.payload()).json()['report_id']
        self.client.force_login(self.pm)
        managers=self.client.post('/mobile/workorder/v2/',self.payload()).json()['report_id']
        self.assertContains(self.client.get('/work-reports/'),f'PPC-{own}')
        self.client.force_login(self.field)
        self.assertContains(self.client.get('/work-reports/'),f'PPC-{own}')
        self.assertNotContains(self.client.get('/work-reports/'),f'PPC-{managers}')
        self.assertEqual(self.client.get(f'/work-reports/{managers}/').status_code,404)
        self.client.force_login(self.pm)
        other=Team.objects.create(business=self.pest,code='other-pest',name='Other pest team')
        member=Membership.objects.create(user=self.pm,team=other,role='manager')
        self.client.post('/ops/switch/',{'membership':member.pk})
        self.assertNotContains(self.client.get('/work-reports/'),f'PPC-{own}')

    def test_retry_is_idempotent_and_stale_team_rejected_before_replay(self):
        payload=self.payload()
        first=self.client.post('/mobile/workorder/v2/',payload)
        retry=self.client.post('/mobile/workorder/v2/',payload)
        self.assertEqual(first.json(),retry.json())
        self.assertEqual(retry['Idempotency-Replayed'],'true')
        self.assertEqual(PestWorkData.objects.count(),1)
        other=Team.objects.create(business=self.pest,code='other',name='Other')
        member=Membership.objects.create(user=self.pm,team=other,role='manager')
        self.client.post('/ops/switch/',{'membership':member.pk})
        self.assertEqual(self.client.post('/mobile/workorder/v2/',payload).status_code,409)
        self.assertEqual(PestWorkData.objects.count(),1)

    def test_forged_nodes_places_dates_and_catalogs_rejected_without_partial_writes(self):
        foreign=ReferenceCatalog.objects.create(business=self.irrigation,version='foreign',name='Other',source_name='fixture')
        for extra in ({'locations':[str(self.private.pk)]},{'nodes':[str(self.catalog.nodes.filter(parent=None).first().pk)]},
                      {'catalog':str(foreign.pk)}, {'date':(timezone.localdate()+timedelta(days=1)).isoformat()},
                      {'team_size':'-1'}, {'nodes':[]}, {'locations':['bad-uuid']}):
            response=self.client.post('/mobile/workorder/v2/',self.payload(**extra))
            self.assertEqual(response.status_code,400,response.content)
        self.assertEqual(WorkReport.all_businesses.count(),0)

    def test_common_irrigation_form_fields_keep_the_same_hours_calculation(self):
        response=self.client.post('/mobile/workorder/v2/',self.payload(
            shift='夜班',team_size='2',third_party_count='1',work_start_time='23:30',work_end_time='01:00'))
        self.assertEqual(response.status_code,200,response.content)
        report=WorkReport.all_businesses.get(pk=response.json()['report_id'])
        self.assertEqual(report.shift,'夜班')
        self.assertEqual(str(report.work_start_time),'23:30:00')
        self.assertEqual(str(report.work_end_time),'01:00:00')
        self.assertEqual(report.third_party_count,1)
        self.assertEqual(float(report.team_hours),3.0)
        self.assertEqual(float(report.third_party_hours),1.5)

    def test_invalid_common_form_values_do_not_create_records(self):
        for values in ({'shift':'invalid'},{'team_size':'0','third_party_count':'0'},
                       {'third_party_count':'-1'},{'work_start_time':'09:00'},
                       {'work_start_time':'bad','work_end_time':'10:00'}):
            response=self.client.post('/mobile/workorder/v2/',self.payload(**values))
            self.assertEqual(response.status_code,400,response.content)
        self.assertFalse(WorkReport.all_businesses.exists())

    def test_plain_account_manager_can_use_hierarchy_and_viewer_cannot_submit(self):
        user=get_user_model().objects.create_user('plain-pest-manager',password='fixture')
        member=Membership.objects.create(user=user,team=self.pt,role='manager')
        self.client.force_login(user)
        self.assertEqual(self.client.get('/api/modal/workorder-data/').status_code,200)
        member.role='viewer';member.save()
        self.assertEqual(self.client.get('/api/modal/workorder-data/').status_code,403)
        self.assertEqual(self.client.post('/mobile/workorder/v2/',self.payload()).status_code,403)

    def test_reference_changes_do_not_relabel_submitted_paths(self):
        report_id=self.client.post('/mobile/workorder/v2/',self.payload()).json()['report_id']
        self.leaf.label='Changed reference';self.leaf.save()
        self.assertContains(self.client.get(f'/work-reports/{report_id}/'),'报封堵工单')
        self.assertNotContains(self.client.get(f'/work-reports/{report_id}/'),'Changed reference')

    def test_building_pin_needs_no_boundary_or_irrigation_station(self):
        response=self.client.post('/ops/locations/new/',{'name':'Visitor centre','code':'VISITOR',
            'kind':'building','map_display':'pin','latitude':'31.125','longitude':'121.25'})
        self.assertEqual(response.status_code,302)
        place=Location.objects.get(code='VISITOR')
        self.assertEqual(place.map_display,'pin')
        self.assertIsNone(place.legacy_zone_id)
        data=next(p for p in self.client.get('/api/zones-payload/').json()['locations'] if p['id']==str(place.pk))
        self.assertEqual(data['map_display'],'pin')
        self.assertEqual(data['kind'],'building')
        self.assertEqual(data['center'],{'lat':31.125,'lng':121.25})
        self.assertEqual(data['boundary'],[])
        # Existing location clients can omit the new option without resetting it.
        self.client.post(f'/ops/locations/{place.pk}/edit/',{'name':'Visitor centre','code':'VISITOR','kind':'building',
            'latitude':'31.125','longitude':'121.25'})
        place.refresh_from_db();self.assertEqual(place.map_display,'pin')
        self.assertContains(self.client.get(f'/ops/locations/{place.pk}/'),'图钉标注')
        self.assertContains(self.client.get('/ops/locations/new/'),'operations/location-editor.js')

    def test_pin_display_keeps_shared_source_boundary_and_permissions(self):
        old=self.zone.active_boundary_points
        response=self.client.post(f'/ops/locations/{self.shared.pk}/edit/',{'name':self.shared.name,'kind':'zone','map_display':'pin'})
        self.assertEqual(response.status_code,404)
        self.client.force_login(self.im)
        response=self.client.post(f'/ops/locations/{self.shared.pk}/edit/',{
            'name':self.shared.name,'code':self.shared.code,'kind':'zone','map_display':'pin'})
        self.assertEqual(response.status_code,302)
        self.zone.refresh_from_db();self.assertEqual(self.zone.active_boundary_points,old)
        self.client.force_login(self.pm)
        for endpoint in ('/api/zones-payload/','/ops/locations.geojson'):
            data=next(p for p in self.client.get(endpoint).json()['locations'] if p['id']==str(self.shared.pk))
            self.assertEqual(data['map_display'],'pin')
            self.assertEqual(data['boundary'],old)
            self.assertIsNotNone(data['center'])

    def test_pin_position_stays_optional_and_invalid_display_mode_rejected(self):
        response=self.client.post('/ops/locations/new/',{'name':'Room without GPS','kind':'room','map_display':'pin'})
        self.assertEqual(response.status_code,302)
        room=Location.objects.get(name='Room without GPS')
        data=next(p for p in self.client.get('/api/zones-payload/').json()['locations'] if p['id']==str(room.pk))
        self.assertIsNone(data['center'])
        self.assertEqual(data['boundary'],[])
        self.assertEqual(self.client.post('/ops/locations/new/',{'name':'Bad style','kind':'building','map_display':'untrusted'}).status_code,200)
        self.assertFalse(Location.objects.filter(name='Bad style').exists())
