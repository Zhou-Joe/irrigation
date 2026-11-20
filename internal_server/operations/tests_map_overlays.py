"""HD imagery overlay API: view permissions, upload validation and calibration."""
import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from . import tests as fixtures
from .models import BusinessArea, MapImageOverlay, Membership, Team


def png_bytes(width=8, height=6):
    buffer = io.BytesIO()
    Image.new('RGB', (width, height), '#3a7d44').save(buffer, format='PNG')
    return buffer.getvalue()


@override_settings(MULTI_TEAM_ENABLED=True)
class MapOverlayTests(TestCase):
    def setUp(self):
        fixtures.WorkspaceTests.setUp(self)
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, True)
        settings = self.settings(MEDIA_ROOT=media)
        settings.enable()
        self.addCleanup(settings.disable)

    def upload(self, as_user, name='北区高清影像', data=None):
        self.client.force_login(as_user)
        payload = {'name': name, 'image': SimpleUploadedFile('hd.png', data or png_bytes(), 'image/png')}
        return self.client.post('/ops/map-overlays/new/', payload)

    def test_member_lists_but_only_managers_write(self):
        self.assertEqual(self.upload(self.field).status_code, 403)
        response = self.upload(self.pm)
        self.assertEqual(response.status_code, 200, response.content)
        item_id = response.json()['overlay']['id']

        self.client.force_login(self.field)
        listing = self.client.get('/ops/map-overlays/').json()
        self.assertTrue(listing['success'])
        self.assertEqual(listing['overlays'], [])
        self.assertEqual(self.client.get(f'/ops/map-overlays/{item_id}/image/').status_code, 404)
        anchors = {'tl_lat': '31.1', 'tl_lng': '121.1', 'tr_lat': '31.1', 'tr_lng': '121.2',
                   'bl_lat': '31.0', 'bl_lng': '121.1'}
        self.assertEqual(self.client.post(f'/ops/map-overlays/{item_id}/calibrate/', anchors).status_code, 403)
        self.assertEqual(self.client.post(f'/ops/map-overlays/{item_id}/delete/').status_code, 403)

    def test_calibration_persists_anchors_and_updates_visibility(self):
        item = self.upload(self.pm).json()['overlay']
        item_id = item['id']
        anchors = {'tl_lat': '31.1', 'tl_lng': '121.1', 'tr_lat': '31.1', 'tr_lng': '121.2',
                   'bl_lat': '31.0', 'bl_lng': '121.1'}
        anchors['calibration_version'] = item['calibration_version']
        response = self.client.post(f'/ops/map-overlays/{item_id}/calibrate/', anchors)
        self.assertEqual(response.status_code, 200, response.content)
        payload = self.client.get('/ops/map-overlays/').json()['overlays'][0]
        self.assertTrue(payload['calibrated'])
        self.assertEqual(payload['anchors']['tl'], [31.1, 121.1])
        self.assertEqual(payload['image_url'], f'/ops/map-overlays/{item_id}/image/')
        response = self.client.get(payload['image_url'])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/png')

        response = self.client.post(f'/ops/map-overlays/{item_id}/update/', {'active': 'false', 'opacity': '0.5'})
        self.assertEqual(response.status_code, 200, response.content)
        payload = self.client.get('/ops/map-overlays/').json()['overlays'][0]
        self.assertFalse(payload['active'])
        self.assertEqual(payload['opacity'], 0.5)

    def test_one_calibration_is_shared_by_all_three_home_maps(self):
        green, _ = BusinessArea.objects.get_or_create(code='landscaping', defaults={'name':'绿化'})
        team = Team.objects.create(business=green, code='hd-green', name='绿化组')
        for field_team in (self.it, team):
            Membership.objects.create(user=self.field, team=field_team, role='field')
        item = self.upload(self.im).json()['overlay']
        item_id = item['id']
        anchors = {'tl_lat':31.1,'tl_lng':121.1,'tr_lat':31.1,'tr_lng':121.2,'bl_lat':31.0,'bl_lng':121.1}
        self.client.force_login(self.admin)
        session = self.client.session
        session['operations_business'] = 'landscaping'
        session.save()
        url = f'/ops/map-overlays/{item_id}/'
        anchors['calibration_version'] = item['calibration_version']
        self.assertTrue(self.client.post(url+'calibrate/', anchors).json()['success'])
        for manager, user in ((True, self.admin), (False, self.field)):
            self.client.force_login(user)
            for business in ('irrigation', 'pest-control', 'landscaping'):
                with self.subTest(manager=manager, business=business):
                    session = self.client.session
                    session['operations_business'] = business
                    session.save()
                    page = self.client.get('/')
                    self.assertContains(page, 'data-hd-visible')
                    self.assertNotContains(page, 'data-hd-manage')
                    settings_url = '/settings/' if business == 'irrigation' else '/ops/locations/'
                    settings_page = self.client.get(settings_url)
                    editor = self.client.get('/ops/locations/imagery/')
                    if manager:
                        self.assertContains(settings_page, '/ops/locations/imagery/')
                        self.assertContains(editor, 'data-hd-manage')
                        self.assertContains(editor, 'imageryMap')
                    else:
                        self.assertNotContains(settings_page, '/ops/locations/imagery/')
                        self.assertEqual(editor.status_code, 403)
                    records = self.client.get('/ops/map-overlays/').json()['overlays']
                    self.assertEqual([row['id'] for row in records], [item_id])
                    self.assertEqual(records[0]['anchors']['tl'], [31.1, 121.1])
                    self.assertEqual(self.client.get(url+'image/').status_code, 200)
                    response = self.client.post(url+'update/', {'opacity':'0.8'})
                    self.assertEqual(response.status_code, 200 if manager else 403)

    def test_stale_and_unversioned_calibrations_preserve_latest_anchors(self):
        item = self.upload(self.pm).json()['overlay']
        url = item['image_url'].replace('/image/', '/calibrate/')
        anchors = {'tl_lat':31.1, 'tl_lng':121.1, 'tr_lat':31.1, 'tr_lng':121.2, 'bl_lat':31, 'bl_lng':121.1}
        first = self.client.post(url, {**anchors, 'calibration_version':item['calibration_version']}).json()['overlay']
        self.assertNotEqual(first['calibration_version'], item['calibration_version'])
        for stale in ({}, {'calibration_version':item['calibration_version']}):
            self.assertEqual(self.client.post(url, {**anchors, 'tl_lat':31.2, **stale}).status_code, 409)
        self.assertEqual(self.client.get('/ops/map-overlays/').json()['overlays'][0], first)
        image = self.client.get(item['image_url'])
        self.assertEqual(image['Cache-Control'], 'private, no-cache')
        self.assertEqual(self.client.get(item['image_url'], HTTP_IF_NONE_MATCH=image['ETag']).status_code, 304)
        self.client.post(item['image_url'].replace('/image/', '/update/'), {'active':'false'})
        self.client.force_login(self.field)
        self.assertEqual(self.client.get(item['image_url'], HTTP_IF_NONE_MATCH=image['ETag']).status_code, 404)

    def test_invalid_uploads_and_coincident_anchors_are_rejected(self):
        self.client.force_login(self.pm)
        self.assertEqual(self.client.post('/ops/map-overlays/new/', {'name': 'x'}).status_code, 400)  # no image
        self.assertEqual(self.upload(self.pm, data=b'not-an-image').status_code, 400)
        response = self.upload(self.pm)
        item_id = response.json()['overlay']['id']
        coincident = {key: '31.1' for key in ('tl_lat', 'tl_lng', 'tr_lat', 'tr_lng', 'bl_lat', 'bl_lng')}
        self.assertEqual(self.client.post(f'/ops/map-overlays/{item_id}/calibrate/', coincident).status_code, 400)
        collinear = {'tl_lat':31.1,'tr_lat':31.1,'bl_lat':31.1,'tl_lng':121.1,'tr_lng':121.2,'bl_lng':121.3}
        self.assertEqual(self.client.post(f'/ops/map-overlays/{item_id}/calibrate/', collinear).status_code,400)
        self.assertFalse(MapImageOverlay.objects.get(pk=item_id).calibrated)

    def test_delete_removes_record_and_file(self):
        item_id = self.upload(self.pm).json()['overlay']['id']
        item = MapImageOverlay.objects.get(pk=item_id)
        stored = item.image.name
        response = self.client.post(f'/ops/map-overlays/{item_id}/delete/')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(MapImageOverlay.objects.filter(pk=item_id).exists())
        from django.conf import settings
        from pathlib import Path
        self.assertFalse((Path(settings.MEDIA_ROOT) / stored).exists())
