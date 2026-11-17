import uuid

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import Zone, Worker, WorkReport
from .models import (AuditEvent, BusinessArea, Location, LocationGrant, Membership, Team,
                     ReferenceCatalog, PestWorkData, PestMaintenancePlan, PestTask)


@override_settings(MULTI_TEAM_ENABLED=True, PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class LocationSelectionTests(TestCase):
    def setUp(self):
        irrigation = BusinessArea.objects.create(code='irrigation', name='灌溉')
        pest = BusinessArea.objects.create(code='pest-control', name='植保')
        self.source = Team.objects.create(business=irrigation, code='irrigation', name='灌溉团队', legacy_irrigation_access=True)
        self.team = Team.objects.create(business=pest, code='pest', name='植保团队')
        self.other = Team.objects.create(business=pest, code='other-pest', name='另一个植保团队')
        self.manager = User.objects.create_user('location-manager')
        self.field = User.objects.create_user('location-field')
        Membership.objects.create(user=self.manager, team=self.team, role='manager')
        Membership.objects.create(user=self.field, team=self.team, role='field')
        self.zone = Zone.objects.create(code='MAP-SHARED', name='地图多选区域', boundary_points=[[
            {'lat': 31.14, 'lng': 121.65}, {'lat': 31.141, 'lng': 121.65}, {'lat': 31.14, 'lng': 121.651}]])
        self.foreign = Location.objects.create(owner_team=self.source, legacy_zone=self.zone, name=self.zone.name)
        self.own = Location.objects.create(owner_team=self.team, kind='building', name='本团队建筑')
        self.off_page = [Location.objects.create(owner_team=self.source, name=f'其他团队地点 {i:02d}',
            latitude=31.15, longitude=121.66) for i in range(35)]
        LocationGrant.objects.create(location=self.foreign, team=self.other)
        self.client.force_login(self.manager)

    def payload(self, locations, action='add'):
        return {'team': self.team.pk, 'scope': 'catalog', 'locations': [str(item.pk) for item in locations],
                'action': action, 'submission_key': str(uuid.uuid4())}

    def test_catalog_geometry_marks_only_other_team_locations_as_selectable(self):
        response = self.client.get('/ops/locations.geojson?scope=catalog')
        self.assertEqual(response.status_code, 200)
        places = {place['id']: place for place in response.json()['locations']}
        self.assertTrue(places[str(self.foreign.pk)]['can_select'])
        self.assertTrue(places[str(self.off_page[-1].pk)]['can_select'])
        self.assertFalse(places[str(self.own.pk)]['can_select'])
        self.assertFalse(places[str(self.foreign.pk)]['can_edit'])
        normal = self.client.get('/ops/locations.geojson').json()['locations']
        self.assertTrue(all(not place['can_select'] for place in normal))

    def test_map_selection_can_submit_locations_beyond_the_list_page(self):
        page = self.client.get('/ops/locations/?scope=catalog')
        self.assertEqual(len(page.context['locations']), 30)
        selected = [self.foreign, *self.off_page]
        payload = self.payload(selected)
        response = self.client.post('/ops/locations/team-visibility/', payload)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['selected_count'], len(selected))
        self.assertEqual(LocationGrant.objects.filter(team=self.team).count(), len(selected))
        self.assertEqual(self.client.post('/ops/locations/team-visibility/', payload).json(), response.json())
        self.client.force_login(self.field)
        places = self.client.get('/ops/locations.geojson').json()['locations']
        self.assertIn(str(self.off_page[-1].pk), {place['id'] for place in places})
        self.client.force_login(self.manager)
        response = self.client.post('/ops/locations/team-visibility/', self.payload([self.foreign], 'remove'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(LocationGrant.objects.filter(location=self.foreign, team=self.team).exists())
        self.assertTrue(LocationGrant.objects.filter(location=self.foreign, team=self.other).exists())
        self.foreign.refresh_from_db(); self.zone.refresh_from_db()
        self.assertEqual(self.foreign.owner_team_id, self.source.pk)
        self.assertEqual(self.zone.boundary_points[0][0], {'lat': 31.14, 'lng': 121.65})

    def test_field_users_cannot_browse_or_apply_catalog_selection(self):
        self.client.force_login(self.field)
        self.assertEqual(self.client.get('/ops/locations.geojson?scope=catalog').status_code, 403)
        self.assertEqual(self.client.post('/ops/locations/team-visibility/', self.payload([self.foreign])).status_code, 403)
        self.assertFalse(LocationGrant.objects.filter(team=self.team).exists())

    def test_mixed_selection_cannot_change_ownership_or_partially_apply(self):
        response = self.client.post('/ops/locations/team-visibility/', self.payload([self.foreign, self.own]))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(LocationGrant.objects.filter(team=self.team).exists())

    def test_explicit_selection_rejects_stale_map_ids_outside_current_filters(self):
        payload = {**self.payload([self.foreign, self.off_page[-1]]), 'q': self.foreign.name}
        response = self.client.post('/ops/locations/team-visibility/', payload)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(LocationGrant.objects.filter(team=self.team).exists())

    def test_filtered_all_except_one_never_selects_another_result_set(self):
        payload = {**self.payload([]), 'all_matching': '1', 'q': self.foreign.name,
                   'excluded_locations': [str(self.foreign.pk)]}
        response = self.client.post('/ops/locations/team-visibility/', payload)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(LocationGrant.objects.filter(team=self.team).exists())
        payload = {**self.payload([]), 'all_matching': '1', 'q': '其他团队地点',
                   'excluded_locations': [str(self.off_page[0].pk)]}
        response = self.client.post('/ops/locations/team-visibility/', payload)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['selected_count'], 34)
        self.assertFalse(LocationGrant.objects.filter(team=self.team, location=self.off_page[0]).exists())
        self.assertFalse(LocationGrant.objects.filter(team=self.team, location=self.foreign).exists())

    def test_retired_irrigation_entry_is_removed_and_map_has_its_own_apply_controls(self):
        page = self.client.get('/ops/locations/?scope=catalog')
        self.assertNotContains(page, '共享灌溉区域')
        self.assertContains(page, 'data-map-selection-toolbar')
        self.assertContains(page, 'location-management.css')
        self.assertContains(page, '应用到本团队')
        self.assertEqual(self.client.get('/ops/locations/link-irrigation/').status_code, 404)
        self.assertEqual(self.client.post('/ops/locations/link-irrigation/', {'zone': self.zone.pk}).status_code, 404)

    def delete_payload(self, place=None, **values):
        return {'team':str(self.team.pk),'location':str((place or self.own).pk),
                'submission_key':str(uuid.uuid4()),**values}

    def test_manager_deletes_native_building_and_grants_once_with_retry(self):
        LocationGrant.objects.create(location=self.own, team=self.other)
        url = f'/ops/locations/{self.own.pk}/delete/'
        data = self.delete_payload()
        self.assertContains(self.client.get('/ops/locations/'), 'data-location-delete=')
        self.assertContains(self.client.get(f'/ops/locations/{self.own.pk}/'), '删除地点')
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(Location.objects.filter(pk=self.own.pk).exists())
        self.assertFalse(LocationGrant.objects.filter(location_id=self.own.pk).exists())
        replay = self.client.post(url, data)
        self.assertEqual(replay.json(), response.json())
        self.assertEqual(AuditEvent.objects.filter(action='location.delete').count(), 1)
        self.assertEqual(self.client.get(f'/ops/locations/{self.own.pk}/').status_code, 404)
        ids = {place['id'] for place in self.client.get('/ops/locations.geojson').json()['locations']}
        self.assertNotIn(str(self.own.pk), ids)
        self.assertTrue(Location.objects.filter(pk=self.foreign.pk).exists())

    def test_delete_requires_ownership_manager_csrf_and_matching_team_and_location(self):
        from django.test import Client
        url = f'/ops/locations/{self.own.pk}/delete/'
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url, self.delete_payload(team=str(self.other.pk))).status_code, 409)
        self.assertEqual(self.client.post(url, self.delete_payload(location=str(self.foreign.pk))).status_code, 400)
        self.assertEqual(self.client.post(f'/ops/locations/{self.foreign.pk}/delete/', self.delete_payload(self.foreign)).status_code, 404)
        csrf = Client(enforce_csrf_checks=True); csrf.force_login(self.manager)
        self.assertEqual(csrf.post(url, self.delete_payload()).status_code, 403)
        self.client.force_login(self.field)
        self.assertEqual(self.client.post(url, self.delete_payload()).status_code, 403)
        self.assertNotContains(self.client.get('/ops/locations/'), 'data-location-delete=')
        self.assertTrue(Location.objects.filter(pk=self.own.pk).exists())

    def test_delete_reports_children_work_plans_and_tasks_without_losing_links(self):
        url = f'/ops/locations/{self.own.pk}/delete/'
        child = Location.objects.create(owner_team=self.team, parent=self.own, name='下级房间', kind='room')
        response = self.client.post(url, self.delete_payload())
        self.assertEqual(response.status_code, 409)
        self.assertIn('下级地点', response.json()['message'])
        child.delete()
        catalog = ReferenceCatalog.objects.create(business=self.team.business, owner_team=self.team,
            name='目录', version='delete-test', source_name='fixture')
        worker = Worker.objects.create(user=self.manager, employee_id='DELETE-WORKER', full_name='测试')
        report = WorkReport.all_businesses.create(worker=worker, date=timezone.localdate(), business_team=self.team)
        detail = PestWorkData.objects.create(report=report, catalog=catalog)
        detail.locations.add(self.own)
        response = self.client.post(url, self.delete_payload())
        self.assertEqual(response.status_code, 409)
        self.assertIn('工单', response.json()['message'])
        self.assertTrue(detail.locations.filter(pk=self.own.pk).exists())
        detail.locations.clear()
        today = timezone.localdate()
        plan = PestMaintenancePlan.objects.create(team=self.team,name='周期计划',catalog=catalog,anchor_date=today,next_cycle=today)
        plan.locations.add(self.own)
        response = self.client.post(url, self.delete_payload())
        self.assertEqual(response.status_code, 409)
        self.assertIn('作业计划', response.json()['message'])
        self.assertTrue(plan.locations.filter(pk=self.own.pk).exists())
        plan.locations.clear()
        PestTask.objects.create(team=self.team,plan=plan,title='任务',catalog=catalog,location=self.own,
            location_label=self.own.name,cycle_start=today,scheduled_date=today,deadline=today)
        response = self.client.post(url, self.delete_payload())
        self.assertEqual(response.status_code, 409)
        self.assertIn('任务', response.json()['message'])
        self.assertTrue(Location.objects.filter(pk=self.own.pk).exists())
        self.assertFalse(AuditEvent.objects.filter(action='location.delete').exists())
