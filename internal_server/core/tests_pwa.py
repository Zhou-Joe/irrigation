"""PWA routing, privacy boundaries, permissions and field-home regressions."""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase
from django.urls import reverse

from .models import Crew, Worker
from .tests_pm import PMFixture


class PublicPWATests(SimpleTestCase):
    def get(self, name):
        return self.client.get(reverse('core:' + name), HTTP_HOST='127.0.0.1')

    def test_manifest_can_be_read_before_login_and_covers_full_site(self):
        response = self.get('pwa_manifest')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/manifest+json')
        data = response.json()
        self.assertEqual(data['scope'], '/')
        self.assertEqual(data['start_url'], '/app/')
        self.assertEqual(data['display'], 'standalone')
        self.assertEqual(data['id'], '/app/')
        self.assertEqual({i['sizes'] for i in data['icons']}, {'192x192', '512x512'})
        self.assertTrue(any(i['purpose'] == 'maskable' for i in data['icons']))
        self.assertTrue(all(item['url'].startswith('/') for item in data['shortcuts']))

    def test_service_worker_has_root_scope_no_stale_http_cache_and_valid_render(self):
        response = self.get('pwa_service_worker')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/javascript')
        self.assertEqual(response['Service-Worker-Allowed'], '/')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertNotIn('{%', response.content.decode())
        self.assertNotIn('{{', response.content.decode())

    def test_offline_page_is_public_and_has_retry_without_private_data(self):
        response = self.get('pwa_offline')
        self.assertContains(response, 'pwaRetry')
        self.assertNotContains(response, 'pm-tasks-data')
        self.assertNotContains(response, 'csrfmiddlewaretoken')
        self.assertNotContains(response, 'anti-leak-watermark')

    def test_public_shell_routes_reject_mutations(self):
        for route in ('pwa_manifest', 'pwa_service_worker', 'pwa_offline'):
            self.assertEqual(self.client.post(reverse('core:' + route), HTTP_HOST='127.0.0.1').status_code, 405)

    def test_home_requires_authentication_and_preserves_return_destination(self):
        response = self.get('app_home')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/login/?next=/app/')


class FieldHomeTests(PMFixture):
    def setUp(self):
        self.client.force_login(self.user)
        clock = patch('django.utils.timezone.localdate', return_value=self.today)
        clock.start()
        self.addCleanup(clock.stop)

    def home(self):
        return self.client.get(reverse('core:app_home'), HTTP_HOST='127.0.0.1')

    def test_worker_gets_entire_field_navigation_and_no_manager_modules(self):
        response = self.home()
        self.assertEqual(response.status_code, 200)
        names = {item['name'] for item in response.context['pwa_modules']}
        self.assertTrue({'dashboard', 'work_reports', 'water_requests', 'inventory_management',
                         'stats_dashboard', 'irrigation_dashboard', 'settings', 'profile'} <= names)
        self.assertFalse({'pm_management', 'project_management', 'user_management'} & names)
        self.assertContains(response, 'pwa-bottom-nav')
        self.assertContains(response, 'manifest.webmanifest')
        self.assertIn('no-store', response['Cache-Control'])

    def test_manager_gets_all_administration_tools(self):
        self.client.force_login(self.manager)
        names = {item['name'] for item in self.home().context['pwa_modules']}
        self.assertTrue({'pm_management', 'project_management', 'user_management'} <= names)

    def test_only_actionable_crew_tasks_are_counted_and_preview_uses_full_deadline(self):
        own = self.order(crew=self.crew)
        own.zones.add(self.zone)
        self.order(days=1, crew=self.crew)
        self.order(days=-1, status='completed', crew=self.crew)
        other_user = User.objects.create_user('pwa-other-worker')
        other_worker = Worker.objects.create(user=other_user, employee_id='PWA-OTHER', full_name='Other worker')
        other_crew = Crew.objects.create(name='Other crew', leader=other_worker)
        self.order(days=-2, crew=other_crew)
        response = self.home()
        self.assertEqual(response.context['app_task_count'], 1)
        self.assertEqual(response.context['app_tasks'][0]['gwo_id'], own.pk)
        self.assertEqual(response.context['app_tasks'][0]['deadline'], own.deadline.isoformat())
        self.assertContains(response, '?pm_gwo_id=' + str(own.pk))

    def test_preview_prioritizes_earliest_deadline_and_count_is_not_limited_to_preview(self):
        for days in range(-5, 1):
            task = self.order(days=days, crew=self.crew)
            task.zones.add(self.zone)
        response = self.home()
        tasks = response.context['app_tasks']
        self.assertEqual(response.context['app_task_count'], 6)
        self.assertEqual(len(tasks), 4)
        self.assertEqual(tasks[0]['scheduled_date'], (self.today - timedelta(days=5)).isoformat())

    def test_crew_member_can_see_shared_tasks(self):
        task = self.order(crew=self.crew)
        member = User.objects.create_user('pwa-crew-member')
        worker = Worker.objects.create(user=member, employee_id='PWA-MEMBER', full_name='Crew member')
        self.crew.members.add(worker)
        self.client.force_login(member)
        self.assertEqual(self.home().context['app_tasks'][0]['gwo_id'], task.pk)

    def test_public_offline_page_does_not_embed_identity_when_authenticated(self):
        response = self.client.get(reverse('core:pwa_offline'), HTTP_HOST='127.0.0.1')
        self.assertNotContains(response, self.user.username)
        self.assertNotContains(response, 'pm-tasks-data')

    def test_home_escapes_job_plan_markup(self):
        self.job.name = '<img src=x onerror=alert(1)>'
        self.job.save()
        self.order(crew=self.crew)
        response = self.home()
        self.assertContains(response, '&lt;img src=x onerror=alert(1)&gt;')
        self.assertNotContains(response, '<img src=x')
