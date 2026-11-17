import io
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from PIL import Image

from core.models import WorkReport
from . import tests as fixtures
from .models import BusinessArea, Team, Membership, Location, ReferenceCatalog, ReferenceNode
from .workorder_media import media_items, prepare_uploads


@override_settings(MULTI_TEAM_ENABLED=True)
class PestMediaTests(TestCase):
    def setUp(self):
        fixtures.WorkspaceTests.setUp(self)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.override = override_settings(PEST_WORKORDER_PRIVATE_ROOT=self.temp.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.building = Location.objects.create(owner_team=self.pt, name='Media building', kind='building')
        self.catalog = ReferenceCatalog.objects.create(business=self.pest, version='media-tests', name='Pest', source_name='fixture')
        self.node = ReferenceNode.objects.create(catalog=self.catalog, label='Bird survey', kind='node', source_line=1, order=1)

    def image(self, name='field.png'):
        data = io.BytesIO()
        Image.new('RGB', (50, 30), '#63856e').save(data, 'PNG')
        return SimpleUploadedFile(name, data.getvalue(), content_type='image/png')

    def video(self):
        return SimpleUploadedFile('field.mp4', b'\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isommp42', content_type='video/mp4')

    def payload(self, **extra):
        return {'team':str(self.pt.pk), 'catalog':str(self.catalog.pk), 'nodes':[str(self.node.pk)],
            'locations':[str(self.building.pk)], 'date':timezone.localdate().isoformat(), 'team_size':'1',
            'submission_key':str(uuid.uuid4()), **extra}

    def submit(self, **extra):
        response = self.client.post('/mobile/workorder/v2/', self.payload(**extra))
        self.assertEqual(response.status_code, 200, response.content)
        return WorkReport.all_businesses.get(pk=response.json()['report_id'])

    def files(self):
        return [path for path in Path(self.temp.name).rglob('*') if path.is_file()]

    def test_form_has_multiple_image_and_video_upload_and_private_display(self):
        response = self.client.get('/api/modal/workorder-data/')
        self.assertEqual(response.status_code, 200)
        html = response.json()['form_html']
        self.assertIn('enctype="multipart/form-data"', html)
        self.assertIn('name="report_media"', html)
        self.assertIn('video/mp4', html)
        self.assertIn('multiple', html)
        report = self.submit(report_media=[self.image(), self.video()])
        self.assertEqual(len(report.photos), 2)
        self.assertEqual(len(self.files()), 2)
        response = self.client.get(f'/work-reports/{report.pk}/')
        self.assertContains(response, '现场图片 / 视频')
        self.assertContains(response, '<video')
        self.assertNotContains(response, '/media/pest_workorders/')

    def test_attachment_reads_follow_report_permissions_and_current_team(self):
        self.client.force_login(self.field)
        report = self.submit(report_media=[self.image()])
        url = media_items(report)[0]['url']
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertIn('no-store', response['Cache-Control'])
        response.close()
        self.client.force_login(self.pm)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        response.close()
        self.client.force_login(self.im)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_field_cannot_read_other_colleagues_media_or_guess_unattached_file(self):
        report = self.submit(report_media=[self.image()])
        url = media_items(report)[0]['url']
        self.client.force_login(self.field)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.pm)
        self.assertEqual(self.client.get(f'/ops/workorders/{report.pk}/media/{uuid.uuid4().hex}.png/').status_code, 404)

    def test_video_supports_bounded_range_requests_and_invalid_ranges(self):
        report = self.submit(report_media=[self.video()])
        url = media_items(report)[0]['url']
        response = self.client.head(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Length'], '24')
        response.close()
        response = self.client.get(url, HTTP_RANGE='bytes=4-7')
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response['Content-Length'], '4')
        self.assertEqual(b''.join(response.streaming_content), b'ftyp')
        response.close()
        response = self.client.get(url, HTTP_RANGE='bytes=-4')
        self.assertEqual(b''.join(response.streaming_content), b'mp42')
        response.close()
        response = self.client.get(url, HTTP_RANGE='bytes=999-1000')
        self.assertEqual(response.status_code, 416)

    def test_invalid_files_are_rejected_without_record_or_partial_files(self):
        bad_files = [SimpleUploadedFile('malware.svg', b'<svg></svg>'),
            SimpleUploadedFile('fake.png', b'<html>bad</html>'),
            SimpleUploadedFile('fake.mp4', b'<html>bad</html>'),
            SimpleUploadedFile('empty.mov', b'')]
        for file in bad_files:
            response = self.client.post('/mobile/workorder/v2/', self.payload(report_media=[self.image(), file]))
            self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(WorkReport.all_businesses.exists())
        self.assertEqual(self.files(), [])

    def test_limits_enforced_before_write(self):
        response = self.client.post('/mobile/workorder/v2/', self.payload(report_media=[self.image(f'{i}.png') for i in range(11)]))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(WorkReport.all_businesses.exists())
        file = self.video()
        file.size = 51 * 1024 * 1024
        with self.assertRaises(ValueError):
            prepare_uploads([file])
        files = [self.video() for _ in range(3)]
        for file in files:
            file.size = 40 * 1024 * 1024
        with self.assertRaises(ValueError):
            prepare_uploads(files)

    def test_edit_retains_attachments_and_explicit_removal_deletes_on_commit(self):
        report = self.submit(report_media=[self.image()])
        original = report.photos[0]
        self.client.post('/mobile/workorder/v2/', self.payload(report_id=str(report.pk), remark='Edited'))
        report.refresh_from_db()
        self.assertEqual(report.photos, [original])
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post('/mobile/workorder/v2/', self.payload(report_id=str(report.pk),
                media_remove=[original], report_media=[self.video()]))
        self.assertEqual(response.status_code, 200, response.content)
        report.refresh_from_db()
        self.assertEqual(len(report.photos), 1)
        self.assertTrue(report.photos[0].endswith('.mp4'))
        self.assertEqual(len(self.files()), 1)

    def test_forged_removal_is_rejected_and_failed_audit_cleans_files_and_record(self):
        response = self.client.post('/mobile/workorder/v2/', self.payload(media_remove=['pest_workorders/9/not-owned.png']))
        self.assertEqual(response.status_code, 400)
        with patch('operations.map_views.audit', side_effect=RuntimeError('fixture failure')):
            with self.assertRaises(RuntimeError):
                self.client.post('/mobile/workorder/v2/', self.payload(report_media=[self.image()]))
        self.assertFalse(WorkReport.all_businesses.exists())
        self.assertEqual(self.files(), [])

    def test_replayed_multipart_submission_does_not_duplicate_files(self):
        data = self.payload(report_media=[self.image()])
        first = self.client.post('/mobile/workorder/v2/', data)
        self.assertEqual(first.status_code, 200, first.content)
        data['report_media'] = [self.image()]
        second = self.client.post('/mobile/workorder/v2/', data)
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(second['Idempotency-Replayed'], 'true')
        self.assertEqual(WorkReport.all_businesses.count(), 1)
        self.assertEqual(len(self.files()), 1)


@override_settings(MULTI_TEAM_ENABLED=True)
class PestMediaCommitTests(TransactionTestCase):
    # This test must reach a real commit: deferred file cleanup runs after the
    # receipt/business transaction, before the HTTP response leaves the view.
    def setUp(self):
        self.pest = BusinessArea.objects.create(code='pest-control', name='植保')
        self.pt = Team.objects.create(business=self.pest, code='pest', name='植保团队')
        self.pm = get_user_model().objects.create_user('pest-media-commit-manager')
        Membership.objects.create(user=self.pm, team=self.pt, role='manager')
        self.client.force_login(self.pm)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.override = override_settings(PEST_WORKORDER_PRIVATE_ROOT=self.temp.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.building = Location.objects.create(owner_team=self.pt, name='Media building', kind='building')
        self.catalog = ReferenceCatalog.objects.create(business=self.pest, version='media-commit', name='Pest', source_name='fixture')
        self.node = ReferenceNode.objects.create(catalog=self.catalog, label='Bird survey', kind='node', source_line=1, order=1)
    image = PestMediaTests.image
    video = PestMediaTests.video
    payload = PestMediaTests.payload
    submit = PestMediaTests.submit
    files = PestMediaTests.files

    def test_failed_old_file_cleanup_does_not_delete_committed_new_attachment(self):
        from . import workorder_media
        report = self.submit(report_media=[self.image()])
        original = report.photos[0]
        delete = workorder_media.delete_uploaded

        def unavailable_old_file(references):
            if original in references:
                raise OSError('fixture: old attachment could not be deleted')
            return delete(references)

        with patch('operations.workorder_media.delete_uploaded', side_effect=unavailable_old_file):
            with self.assertLogs('django.db.backends.base', level='ERROR'):
                response = self.client.post('/mobile/workorder/v2/', self.payload(report_id=str(report.pk),
                    media_remove=[original], report_media=[self.video()]))
        self.assertEqual(response.status_code, 200, response.content)
        report.refresh_from_db()
        self.assertEqual(len(report.photos), 1)
        item = media_items(report)[0]
        self.assertTrue(item['video'])
        response = self.client.get(item['url'])
        self.assertEqual(response.status_code, 200)
        response.close()
