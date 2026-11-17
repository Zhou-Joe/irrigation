from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from .models import BusinessArea, Membership, Team


@override_settings(MULTI_TEAM_ENABLED=True, PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class LandscapingWorkspaceTests(TestCase):
    def setUp(self):
        self.team = Team.objects.get(code='landscaping')
        self.user = User.objects.create_user('green-field', password='fixture-password')
        Membership.objects.create(user=self.user, team=self.team, role='field')
        self.client.force_login(self.user)

    def test_green_account_has_placeholder_and_shared_profile_and_feedback(self):
        response = self.client.get('/')
        self.assertContains(response, '板块已创建，功能待开发。')
        self.assertEqual(response.context['business_choices'], [{'code':'landscaping','label':'绿化'}])
        self.assertEqual({module['name'] for module in response.context['pwa_modules']}, {'dashboard','profile','feedback'})
        self.assertNotContains(response, '地图总览')
        self.assertContains(self.client.get('/ops/profile/'), '绿化团队')
        self.assertEqual(self.client.get('/feedback/').status_code, 200)
        self.assertRedirects(self.client.get('/app/'), '/')

    def test_green_account_cannot_use_other_business_operations(self):
        for path in ('/api/zones-payload/', '/api/modal/workorder-data/', '/work-reports/',
                     '/ops/locations/', '/ops/reports/', '/ops/plans/'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(self.client.post('/mobile/workorder/v2/', {}).status_code, 403)
        self.assertEqual(self.client.post('/ops/switch/', {'business':'irrigation'}).status_code, 403)

    def test_admin_can_switch_to_green_and_back_without_assuming_membership(self):
        business = BusinessArea.objects.create(code='irrigation', name='灌溉')
        Team.objects.create(business=business, code='irrigation', name='灌溉团队', legacy_irrigation_access=True)
        admin = User.objects.create_superuser('green-admin', '', 'fixture-password')
        self.client.force_login(admin)
        response = self.client.post('/ops/switch/', {'business':'landscaping'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertContains(self.client.get('/'), 'data-business="landscaping"')
        response = self.client.post('/ops/switch/', {'business':'irrigation'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/').context['business_selected'], 'irrigation')
        self.assertFalse(Membership.objects.filter(user=admin).exists())
