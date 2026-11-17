from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import User
from django.test import Client, RequestFactory, TestCase, override_settings

from operations.models import BusinessArea, Membership, Team
from .admin import RegistrationRequestAdmin
from .models import Announcement, ManagerProfile, RegistrationRequest, Worker
from .registration_service import approve
from .role_utils import get_user_role


@override_settings(MULTI_TEAM_ENABLED=True, PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class WorkerTypeTests(TestCase):
    def setUp(self):
        business = BusinessArea.objects.create(code='irrigation', name='灌溉')
        self.team = Team.objects.create(business=business, code='irrigation', name='灌溉团队', legacy_irrigation_access=True)
        pest = BusinessArea.objects.create(code='pest-control', name='植保')
        self.pest_team = Team.objects.create(business=pest, code='pest-control', name='植保团队')
        self.green_team = Team.objects.get(code='landscaping')
        self.admin = User.objects.create_superuser('type-admin', '', 'fixture-password')

    def registration(self, index=0, **values):
        return {'full_name': '一线同事', 'username': f'worker-type-{index}', 'password': 'fixture-password',
                'phone': f'130000000{index:02d}', 'department_type': 'field_worker', **values}

    def test_register_approve_profile_and_management_preserve_each_worker_type(self):
        for index, (kind, label) in enumerate(Worker.WORKER_TYPE_CHOICES):
            with self.subTest(kind=kind):
                response = Client().post('/register/', self.registration(index, worker_type=kind))
                self.assertEqual(response.status_code, 302)
                registration = RegistrationRequest.objects.get(username=f'worker-type-{index}')
                self.assertEqual(registration.get_requested_role_display(), label)
                approved = approve(registration.pk, self.admin)
                worker = Worker.objects.get(user=approved.created_user)
                self.assertEqual(worker.worker_type, kind)
                self.assertTrue(check_password('fixture-password', approved.created_user.password))
                self.assertEqual(get_user_role(approved.created_user), 'field_worker')
                membership = Membership.objects.get(user=approved.created_user)
                self.assertEqual(membership.role, 'field')
                self.assertEqual(membership.team.business.code, kind)
                self.client.force_login(approved.created_user)
                if kind == Worker.TYPE_IRRIGATION:
                    self.assertEqual(self.client.get('/profile/').context['profile_data']['type'], label)
                else:
                    self.assertContains(self.client.get('/ops/profile/'), label)
                    dashboard = self.client.get('/')
                    self.assertEqual(dashboard.status_code, 200)
                    self.assertEqual(dashboard.context['business_selected'], kind)
        self.client.force_login(self.admin)
        rows = self.client.get('/user-management/').context['users_list']
        self.assertEqual({row['role_display'] for row in rows}, {label for _, label in Worker.WORKER_TYPE_CHOICES})

    def test_registration_defaults_to_irrigation_and_rejects_invalid_type(self):
        self.assertEqual(Client().post('/register/', self.registration()).status_code, 302)
        self.assertEqual(RegistrationRequest.objects.get().worker_type, Worker.TYPE_IRRIGATION)
        response = Client().post('/register/', self.registration(1, worker_type='super_admin'))
        self.assertContains(response, '请选择有效的一线种类')
        self.assertEqual(RegistrationRequest.objects.count(), 1)

    def test_admin_can_change_type_without_deactivating_or_promoting_account(self):
        user = User.objects.create_user('edit-type')
        worker = Worker.objects.create(user=user, employee_id='TYPE-EDIT', full_name='同事')
        self.client.force_login(self.admin)
        url = f'/user-management/worker/{worker.pk}/edit/'
        response = self.client.post(url, {'worker_type': Worker.TYPE_PEST_CONTROL, 'active': 'true'})
        self.assertEqual(response.status_code, 200)
        worker.refresh_from_db(); user.refresh_from_db()
        self.assertEqual(worker.worker_type, Worker.TYPE_PEST_CONTROL)
        self.assertTrue(worker.active and user.is_active)
        self.assertFalse(user.is_staff or user.is_superuser)
        response = self.client.post(url, {'worker_type': 'invalid', 'full_name': 'must not save'})
        self.assertEqual(response.status_code, 400)
        worker.refresh_from_db(); self.assertEqual(worker.full_name, '同事')
        Membership.objects.create(user=user, team=self.team, role='field')
        self.client.force_login(user)
        self.assertEqual(self.client.post(url, {'worker_type': Worker.TYPE_LANDSCAPING}).status_code, 403)

    def test_worker_attribution_does_not_replace_manager_role_label(self):
        user = User.objects.create_user('manager-with-type')
        ManagerProfile.objects.create(user=user, employee_id='TYPE-M', full_name='经理')
        Worker.objects.create(user=user, employee_id='TYPE-W', full_name='经理', worker_type=Worker.TYPE_PEST_CONTROL)
        self.client.force_login(self.admin)
        rows = self.client.get('/user-management/').context['users_list']
        self.assertTrue(all(row['role_display'] == '管理员' for row in rows if row['user_id'] == user.pk))

    def test_django_admin_approval_uses_the_same_type_and_password_handling(self):
        Client().post('/register/', self.registration(worker_type=Worker.TYPE_LANDSCAPING))
        request = RequestFactory().post('/admin/core/registrationrequest/')
        request.user = self.admin
        model_admin = RegistrationRequestAdmin(RegistrationRequest, admin.site)
        with patch.object(model_admin, 'message_user'):
            model_admin.approve_requests(request, RegistrationRequest.objects.all())
        registration = RegistrationRequest.objects.get()
        self.assertEqual(registration.status, 'approved')
        self.assertEqual(registration.created_user.worker_profile.worker_type, Worker.TYPE_LANDSCAPING)
        self.assertTrue(check_password('fixture-password', registration.created_user.password))

    def test_invalid_pending_type_does_not_create_a_partial_account(self):
        registration = RegistrationRequest.objects.create(username='invalid-type', full_name='同事', phone='000', worker_type='invalid')
        with self.assertRaisesMessage(ValueError, '请选择有效的一线种类'):
            approve(registration.pk, self.admin)
        self.assertFalse(User.objects.filter(username=registration.username).exists())
        registration.refresh_from_db(); self.assertEqual(registration.status, 'pending')

    def test_type_edit_keeps_disabled_account_and_blank_department(self):
        user = User.objects.create_user('disabled-type', is_active=False)
        worker = Worker.objects.create(user=user, employee_id='TYPE-DISABLED', full_name='同事', active=True)
        self.client.force_login(self.admin)
        rows = self.client.get('/user-management/').context['users_list']
        row = next(row for row in rows if row['user_id'] == user.pk)
        self.assertFalse(row['active'])
        self.assertEqual((row['department_code'], row['department_other']), ('', ''))
        response = self.client.post(f'/user-management/worker/{worker.pk}/edit/', {'worker_type':Worker.TYPE_PEST_CONTROL})
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db(); worker.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertEqual((worker.department, worker.department_other), ('', ''))

    def test_worker_api_round_trips_kind_and_rejects_invalid_kind(self):
        self.client.force_login(self.admin)
        response = self.client.post('/api/workers/', {'employee_id':'TYPE-API','full_name':'接口同事',
                                                     'worker_type':Worker.TYPE_PEST_CONTROL})
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()['worker_type'], Worker.TYPE_PEST_CONTROL)
        worker = Worker.objects.get(pk=response.json()['id'])
        self.assertEqual(worker.worker_type, Worker.TYPE_PEST_CONTROL)
        response = self.client.patch(f'/api/workers/{worker.pk}/', {'worker_type':Worker.TYPE_LANDSCAPING}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        worker.refresh_from_db(); self.assertEqual(worker.worker_type, Worker.TYPE_LANDSCAPING)
        response = self.client.patch(f'/api/workers/{worker.pk}/', {'worker_type':'invalid'}, content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_announcements_display_saved_kind_without_changing_manager_labels(self):
        names = {}
        for index, (kind, label) in enumerate(Worker.WORKER_TYPE_CHOICES):
            user = User.objects.create_user(f'notice-type-{index}')
            Worker.objects.create(user=user, employee_id=f'TYPE-NOTICE-{index}', full_name=kind, worker_type=kind)
            names[kind] = label
        announcement = Announcement.objects.create(title='测试', body='正文')
        self.client.force_login(self.admin)
        users = self.client.get(f'/api/announcements/{announcement.pk}/unacked/').json()['users']
        self.assertEqual({row['name']:row['role'] for row in users if row['name'] in names}, names)

    def test_missing_or_ambiguous_destination_team_rolls_back_registration_approval(self):
        self.pest_team.delete()
        Team.objects.create(business=self.team.business,code='unrelated',name='其他灌溉')
        Client().post('/register/', self.registration(worker_type=Worker.TYPE_PEST_CONTROL))
        registration = RegistrationRequest.objects.get()
        with self.assertRaisesMessage(ValueError, '对应团队'):
            approve(registration.pk, self.admin)
        self.assertFalse(User.objects.filter(username=registration.username).exists())
        registration.refresh_from_db(); self.assertEqual(registration.status, 'pending')
