"""Dashboard startup, geometry fidelity, authentication and query regressions."""
import json
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from .models import Zone, Plant, Patch
from .views import _build_dashboard_sidebar_zones, _build_zones_payload, get_zone_center


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class MapDashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser('map-review', 'map@example.test', 'test-only')
        cls.manual = [{'lat': 31.1, 'lng': 121.6}, {'lat': 31.11, 'lng': 121.6}, {'lat': 31.1, 'lng': 121.61}]
        cls.cad = [[{'lat': 31.12, 'lng': 121.62}, {'lat': 31.13, 'lng': 121.62}, {'lat': 31.12, 'lng': 121.63}]]
        cls.zone = Zone.objects.create(code='MAP-1', name='Map zone', boundary_points=cls.manual,
                                      dxf_boundary_points=cls.cad, boundary_source='dxf',
                                      remarks=json.dumps([{'date': '2026-10-23', 'content': 'Check filter'}]))
        Plant.objects.create(zone=cls.zone, name='Tree')

    def setUp(self):
        self.client.force_login(self.user)

    def test_html_never_builds_full_geometry_payload(self):
        with patch('core.views._build_zones_payload', side_effect=AssertionError('Geometry on HTML path')):
            response = self.client.get('/', HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'MAP-1')
        self.assertContains(response, 'remark-badge-pending')
        self.assertContains(response, 'vendor/leaflet/leaflet.js')
        self.assertContains(response, 'vendor/marked/marked.min.js')
        self.assertNotContains(response, 'unpkg.com')
        self.assertNotContains(response, 'cdn.jsdelivr.net')

    def test_sidebar_is_two_queries_and_excludes_geometry_and_histories(self):
        with self.assertNumQueries(2):
            zones = _build_dashboard_sidebar_zones()
        row = next(z for z in zones if z['id'] == self.zone.pk)
        self.assertEqual(row['plant_names'], ['Tree'])
        self.assertTrue(row['has_remarks'])
        for name in ('boundary_points', 'dxf_boundary_points', 'recent_workorders', 'remarks'):
            self.assertNotIn(name, row)

    def test_patch_filter_excludes_station_equipment_and_unused_locations(self):
        area = Patch.objects.create(code='FILTER-CCU1', name='West gate')
        Patch.objects.create(code='FILTER-CCU2', name='Unused location')
        station = Patch.objects.create(code='Station-FILTER-123', name='Station 123', parent=area)
        Zone.objects.filter(pk=self.zone.pk).update(patch=area)
        # Even a legacy direct zone link must not turn equipment into an area.
        Zone.objects.create(code='STATION-ZONE', name='Legacy link', patch=station)
        response = self.client.get('/', HTTP_HOST='127.0.0.1')
        choices = json.loads(response.context['patches_json'])
        self.assertEqual(choices, [{'id': area.pk, 'name': area.name, 'code': area.code}])
        self.assertTrue(Patch.objects.filter(pk=station.pk).exists())

    def test_patch_filter_keeps_used_inactive_and_nested_custom_areas(self):
        parent = Patch.objects.create(code='FILTER-CUSTOM', name='Parent')
        inactive = Patch.objects.create(code='FILTER-CCU35', name='Road', active=False)
        nested = Patch.objects.create(code='FILTER-CUSTOM-1', name='Station garden', parent=parent)
        Zone.objects.filter(pk=self.zone.pk).update(patch=inactive)
        Zone.objects.create(code='CUSTOM-ZONE', name='Garden', patch=nested)
        response = self.client.get('/', HTTP_HOST='127.0.0.1')
        choices = json.loads(response.context['patches_json'])
        self.assertEqual([row['id'] for row in choices], [inactive.pk, nested.pk])

    def test_unassigned_zones_do_not_offer_unrelated_patch_filters(self):
        Patch.objects.create(code='FILTER-CCU1', name='Unused area')
        Patch.objects.create(code='station-FILTER-1', name='Station 1')
        response = self.client.get('/', HTTP_HOST='127.0.0.1')
        self.assertEqual(json.loads(response.context['patches_json']), [])
        self.assertContains(response, 'MAP-1')

    def test_map_payload_preserves_active_cad_geometry_and_details(self):
        today = date(2026, 10, 23)
        zones = _build_zones_payload(today, today - timedelta(days=7))
        row = next(z for z in zones if z['id'] == self.zone.pk)
        self.assertEqual(row['boundary_points'], self.cad)
        self.assertTrue(row['has_remarks'])
        self.assertEqual(row['remarks'][0]['content'], 'Check filter')
        self.assertIn('recent_workorders', row)
        self.assertEqual(row['plant_count'], 1)

    def test_payload_uses_configured_local_date_and_compact_json(self):
        local_day = date(2026, 11, 1)
        with patch('core.views.timezone.localdate', return_value=local_day), patch(
                'core.views._build_zones_payload', return_value=[{'name': '中文', 'id': 1}]) as build:
            response = self.client.get('/api/zones-payload/', HTTP_HOST='127.0.0.1')
        build.assert_called_once_with(local_day, local_day - timedelta(days=7))
        self.assertEqual(response.json(), [{'name': '中文', 'id': 1}])
        self.assertEqual(response.content.decode(), '[{"name":"中文","id":1}]')
        self.assertIn('private', response['Cache-Control'])

    def test_no_per_zone_query_growth(self):
        today = date(2026, 10, 23)
        with CaptureQueriesContext(connection) as first:
            _build_zones_payload(today, today - timedelta(days=7))
        for n in range(12):
            Zone.objects.create(code=f'MAP-{n+2}', name='Another zone', boundary_points=self.manual)
        with CaptureQueriesContext(connection) as many:
            _build_zones_payload(today, today - timedelta(days=7))
        self.assertEqual(len(many), len(first))

    def test_anonymous_visitors_cannot_read_map_data(self):
        self.client.logout()
        for url in ('/', '/api/zones-payload/', '/api/pipelines-payload/'):
            response = self.client.get(url, HTTP_HOST='127.0.0.1')
            self.assertEqual(response.status_code, 401 if url.startswith('/api/') else 302)
            if url.startswith('/api/'):
                self.assertIn('error', response.json())

    def test_empty_leading_cad_groups_and_malformed_vertices_do_not_break_the_map(self):
        boundary = [[], [[{'lat': None, 'lng': 121}, {'lat': 'bad', 'lng': 121}]], [self.cad]]
        self.assertEqual(get_zone_center(boundary), get_zone_center(self.cad))
        Zone.objects.filter(pk=self.zone.pk).update(dxf_boundary_points=boundary)
        response = self.client.get('/api/zones-payload/', HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]['center'], get_zone_center(self.cad))

    def test_coordinate_centers_preserve_precision_and_handle_empty_data(self):
        self.assertEqual(get_zone_center([['31.123456789', '121.123456789']]),
                         {'lat': 31.123457, 'lng': 121.123457})
        for boundary in (None, [], [[], []], [{'lat': 999, 'lng': 121}]):
            self.assertIsNone(get_zone_center(boundary))
