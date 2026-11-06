"""The ordinary editor must edit the same boundary as the homepage."""
import json

from django.contrib.auth.models import User
from django.test import TestCase

from core.models import Zone


class ZoneEditorSourceTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser('zone-source', '', 'fixture'))
        self.manual = [[{'lat': 31.14, 'lng': 121.65}, {'lat': 31.141, 'lng': 121.65},
                        {'lat': 31.14, 'lng': 121.651}]]
        self.dxf = [[{'lat': 31.15, 'lng': 121.66}, {'lat': 31.151, 'lng': 121.66},
                     {'lat': 31.15, 'lng': 121.661}]]
        self.zone = Zone.objects.create(code='editor-source', name='Source fixture',
            boundary_points=self.manual, dxf_boundary_points=self.dxf,
            boundary_source='dxf', dxf_boundary_source='fixture.dxf')
        self.url = f'/settings/zone/{self.zone.pk}/'

    def test_editor_loads_active_dxf_and_identifies_source(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.context['boundary_json']), self.dxf)
        self.assertEqual(response.context['boundary_edit_source'], 'dxf')
        self.assertContains(response, 'fixture.dxf')
        self.assertContains(response, 'name="boundary_edit_source" value="dxf"')

    def test_save_changes_active_dxf_without_touching_manual_backup(self):
        changed = [[dict(p, lat=p['lat'] + .001) for p in self.dxf[0]]]
        response = self.client.post(self.url, {'boundary_points': json.dumps(changed),
            'boundary_edit_source': 'dxf'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200, response.content)
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.boundary_points, self.manual)
        self.assertEqual(self.zone.dxf_boundary_points, [changed[0] + [changed[0][0]]])
        self.assertEqual(self.zone.boundary_source, 'dxf')
        self.assertEqual(self.zone.dxf_boundary_source, 'fixture.dxf')
        payload = self.client.get('/api/zones-payload/').json()[0]
        self.assertEqual(payload['boundary_points'], self.zone.dxf_boundary_points)
        self.assertEqual(json.loads(self.client.get(self.url).context['boundary_json']), payload['boundary_points'])

    def test_manual_source_edits_preserve_inactive_dxf(self):
        self.zone.boundary_source = 'manual'
        self.zone.save()
        response = self.client.get(self.url)
        self.assertEqual(json.loads(response.context['boundary_json']), self.manual)
        response = self.client.post(self.url, {'boundary_points': json.dumps(self.manual),
            'boundary_edit_source': 'manual'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.dxf_boundary_points, self.dxf)
        self.assertEqual(self.zone.boundary_source, 'manual')

    def test_stale_or_invalid_form_cannot_modify_other_boundary_or_metadata(self):
        for params, status in [
            ({'boundary_edit_source': 'manual', 'boundary_points': json.dumps(self.manual)}, 409),
            ({'boundary_points': json.dumps(self.manual)}, 409),
            ({'boundary_edit_source': 'dxf', 'boundary_points': 'invalid'}, 400),
            ({'boundary_edit_source': 'dxf', 'boundary_points': '[]'}, 400),
        ]:
            params['name'] = 'Must not save'
            response = self.client.post(self.url, params, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(response.status_code, status, response.content)
            self.zone.refresh_from_db()
            self.assertEqual(self.zone.name, 'Source fixture')
            self.assertEqual(self.zone.boundary_points, self.manual)
            self.assertEqual(self.zone.dxf_boundary_points, self.dxf)
