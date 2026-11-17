import io
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils.datastructures import MultiValueDict
from PIL import Image

from .models import BusinessArea, Feedback, FeedbackPhoto, FeedbackAttachment, Membership, Team, AuditEvent
from .feedback import FeedbackForm


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

    def attachment(self, name='工作记录.xlsx', content=b'private attachment bytes'):
        return SimpleUploadedFile(name, content, content_type='application/octet-stream')

    def submit_with_files(self, **changes):
        response=self.client.post('/feedback/',self.data(photos=[self.image()],attachments=[self.attachment()],**changes))
        self.assertEqual(response.status_code,302,response.content)
        return Feedback.objects.order_by('-created_at').first()

    def action_url(self, item):
        return reverse('core:feedback_action',args=[item.pk])

    def action_data(self, action='status', status='completed', **changes):
        return {'action':action,'status':status,'context_team':str(self.irrigation.pk),**changes}

    def test_documents_and_active_content_are_private_downloads_with_original_names(self):
        response=self.client.post('/feedback/',self.data(attachments=[self.attachment(),
            self.attachment('说明.html',b'<script>alert(1)</script>')],status='completed'))
        self.assertEqual(response.status_code,302,response.content)
        item=Feedback.objects.get();self.assertEqual(item.status,'open')
        self.assertEqual(item.attachments.count(),2)
        for file in item.attachments.all():
            self.assertTrue(file.storage_name.endswith('.bin'))
            response=self.client.get(reverse('core:feedback_attachment',args=[file.pk]))
            self.assertEqual(response.status_code,200)
            self.assertEqual(response['Content-Type'],'application/octet-stream')
            self.assertTrue(response['Content-Disposition'].startswith('attachment;'))
            self.assertEqual(response['X-Content-Type-Options'],'nosniff')
            self.assertIn('sandbox',response['Content-Security-Policy'])
            self.assertIn('no-store',response['Cache-Control'])
            self.assertEqual(b''.join(response.streaming_content),(Path(self.temp.name)/file.storage_name).read_bytes())
            response.close()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('core:feedback_attachment',args=[file.pk])).status_code,404)

    def test_owner_team_administrator_and_superuser_can_set_both_statuses(self):
        item=self.submit_with_files();manager=User.objects.create_user('feedback-team-admin')
        Membership.objects.create(user=manager,team=self.irrigation,role='manager')
        for user,status in ((self.user,'completed'),(manager,'open'),(self.admin,'completed')):
            self.client.force_login(user)
            response=self.client.post(self.action_url(item),self.action_data(status=status))
            self.assertEqual(response.status_code,200,response.content)
            item.refresh_from_db();self.assertEqual(item.status,status)
            self.assertEqual(response.json()['label'],dict(Feedback.STATUS_CHOICES)[status])
        self.assertEqual(item.photos.count(),1);self.assertEqual(item.attachments.count(),1)
        self.assertEqual(AuditEvent.objects.filter(action='feedback.status').count(),3)

    def test_pest_author_and_team_administrator_can_manage_feedback_and_photos(self):
        self.client.force_login(self.other)
        item=self.submit_with_files(context_team=self.pest.pk)
        context={'context_team':self.pest.pk}
        response=self.client.post(self.action_url(item),self.action_data(**context))
        self.assertEqual(response.status_code,200,response.content)
        manager=User.objects.create_user('pest-feedback-manager')
        Membership.objects.create(user=manager,team=self.pest,role='manager')
        self.client.force_login(manager)
        photo=item.photos.get();file=item.attachments.get()
        with self.captureOnCommitCallbacks(execute=True):
            response=self.client.post(reverse('core:feedback_file_delete',args=[item.pk,'photos',photo.pk]),context)
        self.assertEqual(response.status_code,200,response.content)
        self.assertFalse((Path(self.temp.name)/photo.storage_name).exists())
        self.assertTrue((Path(self.temp.name)/file.storage_name).exists())
        with self.captureOnCommitCallbacks(execute=True):
            response=self.client.post(self.action_url(item),self.action_data('delete',**context))
        self.assertEqual(response.status_code,200,response.content)
        self.assertFalse((Path(self.temp.name)/file.storage_name).exists())
        self.assertNotContains(self.client.get('/feedback/'),item.message)

    def test_colleague_cannot_change_status_delete_feedback_or_remove_attachments(self):
        item=self.submit_with_files();file=item.attachments.get()
        peer=User.objects.create_user('feedback-peer')
        Membership.objects.create(user=peer,team=self.irrigation,role='field')
        for user,context,expected in ((peer,self.irrigation.pk,403),(self.other,self.pest.pk,404)):
            self.client.force_login(user)
            for operation in ('status','delete'):
                response=self.client.post(self.action_url(item),self.action_data(operation,context_team=str(context)))
                self.assertEqual(response.status_code,expected)
            url=reverse('core:feedback_file_delete',args=[item.pk,'attachments',file.pk])
            self.assertEqual(self.client.post(url,{'context_team':context}).status_code,expected)
        item.refresh_from_db();self.assertEqual(item.status,'open');self.assertIsNone(item.deleted_at)
        self.assertTrue((Path(self.temp.name)/file.storage_name).exists())
        self.client.force_login(peer)
        response=self.client.get('/feedback/')
        self.assertContains(response,item.message)
        self.assertNotContains(response,'data-feedback-action="status"')
        self.assertNotContains(response,'data-feedback-action="delete"')

    def test_status_requires_post_csrf_valid_status_and_current_team_context(self):
        item=self.submit_with_files();url=self.action_url(item)
        self.assertEqual(self.client.get(url).status_code,405)
        self.assertEqual(self.client.post(url,self.action_data(status='invalid')).status_code,400)
        self.assertEqual(self.client.post(url,self.action_data(context_team=str(self.pest.pk))).status_code,409)
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.user)
        self.assertEqual(csrf.post(url,self.action_data()).status_code,403)
        item.refresh_from_db();self.assertEqual(item.status,'open')

    def test_file_removal_keeps_feedback_and_other_files_and_checks_parent_identity(self):
        item=self.submit_with_files();file=item.attachments.get();photo=item.photos.get()
        other=self.submit_with_files(message='Second feedback')
        url=reverse('core:feedback_file_delete',args=[other.pk,'attachments',file.pk])
        self.assertEqual(self.client.post(url,{'context_team':self.irrigation.pk}).status_code,404)
        url=reverse('core:feedback_file_delete',args=[item.pk,'attachments',file.pk])
        with self.captureOnCommitCallbacks(execute=True):
            response=self.client.post(url,{'context_team':self.irrigation.pk})
        self.assertEqual(response.status_code,200,response.content)
        self.assertFalse(FeedbackAttachment.objects.filter(pk=file.pk).exists())
        self.assertFalse((Path(self.temp.name)/file.storage_name).exists())
        self.assertTrue((Path(self.temp.name)/photo.storage_name).exists())
        self.assertIsNone(Feedback.objects.get(pk=item.pk).deleted_at)
        self.assertEqual(self.client.get(reverse('core:feedback_attachment',args=[file.pk])).status_code,404)

    def test_deleting_feedback_removes_files_hides_it_and_does_not_resurrect_on_replay(self):
        key=str(uuid.uuid4());item=self.submit_with_files(submission_key=key)
        photo=item.photos.get();file=item.attachments.get()
        names=[photo.storage_name,file.storage_name]
        with self.captureOnCommitCallbacks(execute=True):
            response=self.client.post(self.action_url(item),self.action_data('delete'))
        self.assertEqual(response.status_code,200,response.content)
        item.refresh_from_db();self.assertIsNotNone(item.deleted_at)
        self.assertFalse(item.photos.exists());self.assertFalse(item.attachments.exists())
        self.assertTrue(all(not (Path(self.temp.name)/name).exists() for name in names))
        self.assertNotContains(self.client.get('/feedback/'),item.message)
        self.assertEqual(self.client.get('/feedback/',{'team':self.irrigation.pk}).status_code,200)
        self.assertEqual(self.client.get(reverse('core:feedback_photo',args=[photo.pk])).status_code,404)
        self.assertEqual(self.client.post(self.action_url(item),self.action_data()).status_code,404)
        self.assertEqual(self.client.post(self.action_url(item),self.action_data('delete')).status_code,200)
        response=self.client.post('/feedback/',self.data(photos=[self.image()],attachments=[self.attachment()],submission_key=key))
        self.assertEqual(response.status_code,400)
        self.assertEqual(Feedback.objects.count(),1)
        self.assertFalse(Feedback.objects.filter(deleted_at__isnull=True).exists())
        self.assertEqual(AuditEvent.objects.filter(action='feedback.delete').count(),1)

    def test_duplicate_upload_is_idempotent_and_preserves_later_status(self):
        key=str(uuid.uuid4());item=self.submit_with_files(submission_key=key)
        self.client.post(self.action_url(item),self.action_data())
        response=self.client.post('/feedback/',self.data(photos=[self.image()],attachments=[self.attachment()],submission_key=key))
        self.assertEqual(response.status_code,302)
        self.assertEqual(Feedback.objects.count(),1)
        self.assertEqual(FeedbackPhoto.objects.count(),1);self.assertEqual(FeedbackAttachment.objects.count(),1)
        item.refresh_from_db();self.assertEqual(item.status,'completed')
        response=self.client.post('/feedback/',self.data(photos=[self.image()],
            attachments=[self.attachment(content=b'changed bytes')],submission_key=key))
        self.assertEqual(response.status_code,400)
        self.assertEqual(FeedbackAttachment.objects.count(),1)

    def test_attachment_size_count_and_combined_limits_are_checked_before_storage(self):
        def upload(size):
            file=self.attachment();file.size=size;return file
        mb=1024*1024
        cases=[([upload(50*mb+1)],[]),([upload(1) for _ in range(11)],[]),
               ([upload(50*mb),upload(50*mb),upload(1)],[]),
               ([upload(1) for _ in range(6)],[self.image() for _ in range(5)])]
        for files,photos in cases:
            form=FeedbackForm(self.data(),MultiValueDict({'attachments':files,'photos':photos}))
            self.assertFalse(form.is_valid())
        form=FeedbackForm(self.data(),MultiValueDict({'attachments':[upload(50*mb),upload(50*mb)]}))
        self.assertTrue(form.is_valid(),form.errors)
        self.assertFalse(Feedback.objects.exists());self.assertEqual(list(Path(self.temp.name).rglob('*')),[])

    def test_failed_file_or_database_write_cleans_all_staged_files(self):
        with patch('operations.feedback.FeedbackAttachment.objects.bulk_create',side_effect=RuntimeError('database failure')):
            with self.assertRaises(RuntimeError):self.submit_with_files()
        self.assertFalse(Feedback.objects.exists())
        self.assertFalse(FeedbackPhoto.objects.exists());self.assertFalse(FeedbackAttachment.objects.exists())
        self.assertEqual(list(Path(self.temp.name).rglob('*')),[])
        with patch('operations.feedback.Path.open',side_effect=OSError('storage failure')):
            response=self.client.post('/feedback/',self.data(attachments=[self.attachment()]))
        self.assertEqual(response.status_code,400)
        self.assertFalse(Feedback.objects.exists());self.assertEqual(list(Path(self.temp.name).rglob('*')),[])

    def test_failed_delete_transaction_keeps_rows_and_files(self):
        item=self.submit_with_files();names=[item.photos.get().storage_name,item.attachments.get().storage_name]
        with self.captureOnCommitCallbacks(execute=True),patch('operations.feedback.AuditEvent.objects.create',side_effect=RuntimeError('audit failure')):
            with self.assertRaises(RuntimeError):self.client.post(self.action_url(item),self.action_data('delete'))
        item.refresh_from_db();self.assertIsNone(item.deleted_at)
        self.assertTrue(item.photos.exists());self.assertTrue(item.attachments.exists())
        self.assertTrue(all((Path(self.temp.name)/name).exists() for name in names))

    def test_attachment_storage_path_cannot_escape_its_feedback_folder(self):
        item=self.submit_with_files();file=item.attachments.get()
        for invalid in ('../outside.bin',f'{uuid.uuid4()}/{file.pk}.bin'):
            file.storage_name=invalid;file.save(update_fields=['storage_name'])
            self.assertEqual(self.client.get(reverse('core:feedback_attachment',args=[file.pk])).status_code,404)
