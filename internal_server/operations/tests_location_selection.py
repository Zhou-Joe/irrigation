import uuid

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from core.models import Zone
from .models import BusinessArea, Location, LocationGrant, Membership, Team


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
