"""HD imagery overlay API: view permissions, upload validation and calibration."""
import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from . import tests as fixtures
from .models import MapImageOverlay


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
        self.assertEqual(len(listing['overlays']), 1)
        self.assertFalse(listing['overlays'][0]['calibrated'])
        anchors = {'tl_lat': '31.1', 'tl_lng': '121.1', 'tr_lat': '31.1', 'tr_lng': '121.2',
                   'bl_lat': '31.0', 'bl_lng': '121.1'}
        self.assertEqual(self.client.post(f'/ops/map-overlays/{item_id}/calibrate/', anchors).status_code, 403)
        self.assertEqual(self.client.post(f'/ops/map-overlays/{item_id}/delete/').status_code, 403)

    def test_calibration_persists_anchors_and_updates_visibility(self):
        item_id = self.upload(self.pm).json()['overlay']['id']
        anchors = {'tl_lat': '31.1', 'tl_lng': '121.1', 'tr_lat': '31.1', 'tr_lng': '121.2',
                   'bl_lat': '31.0', 'bl_lng': '121.1'}
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

    def test_invalid_uploads_and_coincident_anchors_are_rejected(self):
        self.client.force_login(self.pm)
        self.assertEqual(self.client.post('/ops/map-overlays/new/', {'name': 'x'}).status_code, 400)  # no image
        self.assertEqual(self.upload(self.pm, data=b'not-an-image').status_code, 400)
        response = self.upload(self.pm)
        item_id = response.json()['overlay']['id']
        coincident = {key: '31.1' for key in ('tl_lat', 'tl_lng', 'tr_lat', 'tr_lng', 'bl_lat', 'bl_lng')}
        self.assertEqual(self.client.post(f'/ops/map-overlays/{item_id}/calibrate/', coincident).status_code, 400)
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
