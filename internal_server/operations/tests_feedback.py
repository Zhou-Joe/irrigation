import io
import tempfile
import uuid
from pathlib import Path

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from PIL import Image

from .models import BusinessArea, Feedback, FeedbackPhoto, Membership, Team


@override_settings(ALLOWED_HOSTS=['testserver'], MULTI_TEAM_ENABLED=True)
class FeedbackTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.override = override_settings(FEEDBACK_PRIVATE_ROOT=self.temp.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        irrigation = BusinessArea.objects.create(code='irrigation', name='灌溉')
        pest = BusinessArea.objects.create(code='pest-control', name='植保')
        self.irrigation = Team.objects.create(business=irrigation, code='irrigation', name='灌溉团队', legacy_irrigation_access=True)
        self.pest = Team.objects.create(business=pest, code='pest', name='植保团队')
        self.user = User.objects.create_user('feedback-worker')
        from core.models import Worker
        Worker.objects.create(user=self.user, employee_id='FB-W', full_name='Feedback colleague')
        self.other = User.objects.create_user('pest-colleague')
        self.admin = User.objects.create_superuser('feedback-admin', 'admin@example.invalid', 'fixture')
        Membership.objects.create(user=self.user, team=self.irrigation, role='field')
        Membership.objects.create(user=self.other, team=self.pest, role='field')
        self.client.force_login(self.user)

    def data(self, **values):
        return {'message': 'Please make the map easier to use.', 'context_team': self.irrigation.pk,
                'submission_key': str(uuid.uuid4()), **values}

    def image(self, name='illustration.png'):
        data = io.BytesIO()
        Image.new('RGB', (80, 60), '#5b8f73').save(data, 'PNG')
        return SimpleUploadedFile(name, data.getvalue(), content_type='image/png')

    def test_single_input_and_navigation_available_to_both_teams(self):
        for user in (self.user, self.other):
            self.client.force_login(user)
            response = self.client.get('/feedback/')
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, '反馈与建议')
            self.assertContains(response, 'name="message"', count=1)
            self.assertContains(response, 'href="/feedback/"')
            self.assertNotContains(response, 'name="feedback_type"')
            self.assertContains(response, 'name="photos"')

    def test_photo_and_message_save_with_server_selected_team(self):
        response = self.client.post('/feedback/', self.data(photos=[self.image()], team=self.pest.pk))
        self.assertRedirects(response, '/feedback/')
        item = Feedback.objects.get()
        self.assertEqual(item.team, self.irrigation)
        self.assertEqual(item.author, self.user)
        photo = item.photos.get()
        self.assertTrue((Path(self.temp.name) / photo.storage_name).is_file())
        url = f'/feedback/photos/{photo.pk}/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/jpeg')
        self.assertIn('no-store', response['Cache-Control'])
        response.close()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertNotContains(self.client.get('/feedback/'), item.message)

    def test_admin_filters_by_team_and_sees_both_team_categories(self):
        self.client.post('/feedback/', self.data(message='Irrigation feedback'))
        self.client.force_login(self.other)
        self.client.post('/feedback/', self.data(message='Plant protection feedback', context_team=self.pest.pk))
        self.client.force_login(self.admin)
        response = self.client.get('/feedback/')
        self.assertContains(response, 'Irrigation feedback')
        self.assertContains(response, 'Plant protection feedback')
        self.assertContains(response, '灌溉团队')
        self.assertContains(response, '植保团队')
        response = self.client.get('/feedback/', {'team': self.pest.pk})
        self.assertContains(response, 'Plant protection feedback')
        self.assertNotContains(response, 'Irrigation feedback')
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/feedback/', {'team': self.pest.pk}).status_code, 404)

    def test_empty_bad_and_excess_photos_do_not_create_partial_feedback(self):
        for changes in ({'message': ' '}, {'message': 'x' * 5001},
                {'photos': [SimpleUploadedFile('fake.png', b'<html>not an image</html>')]},
                {'photos': [self.image(f'p{i}.png') for i in range(6)]}):
            response = self.client.post('/feedback/', self.data(**changes))
            self.assertEqual(response.status_code, 400)
            self.assertFalse(Feedback.objects.exists())
            self.assertFalse(FeedbackPhoto.objects.exists())
        self.assertEqual(list(Path(self.temp.name).rglob('*.jpg')), [])

    def test_stale_team_context_and_duplicate_submission_are_handled(self):
        self.assertEqual(self.client.post('/feedback/', self.data(context_team=self.pest.pk)).status_code, 400)
        data = self.data()
        self.assertEqual(self.client.post('/feedback/', data).status_code, 302)
        self.assertEqual(self.client.post('/feedback/', data).status_code, 302)
        self.assertEqual(Feedback.objects.count(), 1)
        self.assertEqual(self.client.post('/feedback/', {**data, 'message': 'Changed'}).status_code, 400)
        self.assertEqual(Feedback.objects.count(), 1)

    def test_feedback_is_escaped_and_requires_login_membership_and_csrf(self):
        self.client.post('/feedback/', self.data(message='<script>alert(1)</script>'))
        response = self.client.get('/feedback/')
        self.assertContains(response, '&lt;script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.user)
        self.assertEqual(csrf.post('/feedback/', self.data()).status_code, 403)
        Membership.objects.filter(user=self.user).update(active=False)
        self.assertEqual(self.client.get('/feedback/').status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get('/feedback/').status_code, 302)
