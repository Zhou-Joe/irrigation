"""Execution boundaries, task ownership, and import identity regressions."""
import base64
import io
import json
import tempfile
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import AIConversation, AIExecutionLease, AISettings, Patch, Worker


class BusinessOperationsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('operations-manager', is_staff=True)
        self.client.force_login(self.user)

    def configure_ai(self):
        AISettings.objects.update_or_create(pk=1, defaults=dict(enabled=True,
            api_base_url='https://fixture.invalid', api_key='fixture', model_name='fixture'))

    def chat(self, **body):
        return self.client.post('/api/ai/chat', json.dumps({'message':'Fixture', **body}),
            content_type='application/json')

    def test_unstarted_stream_releases_capacity_and_same_user_is_limited(self):
        self.configure_ai()
        response = self.chat()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(AIExecutionLease.objects.count(), 1)
        blocked = self.chat()
        self.assertEqual(blocked.status_code, 409)
        response.close()
        self.assertFalse(AIExecutionLease.objects.exists())

    def test_fourth_analysis_cannot_occupy_last_sync_worker(self):
        self.configure_ai()
        for number in range(3):
            owner = User.objects.create_user(f'busy-{number}', is_staff=True)
            conversation = AIConversation.objects.create(id=f'u{owner.pk}-abcdef12', owner=owner)
            AIExecutionLease.objects.create(conversation=conversation, owner=owner,
                expires_at=timezone.now()+timedelta(minutes=1))
        self.assertEqual(self.chat().status_code, 429)
        self.assertEqual(AIExecutionLease.objects.count(), 3)

    def test_cancel_and_history_use_only_owned_conversations(self):
        self.configure_ai()
        own = AIConversation.objects.create(id=f'u{self.user.pk}-abcdef12', owner=self.user)
        foreign_user = User.objects.create_user('foreign-manager', is_staff=True)
        foreign = AIConversation.objects.create(id=f'u{foreign_user.pk}-abcdef12', owner=foreign_user)
        lease = AIExecutionLease.objects.create(conversation=own, owner=self.user,
            expires_at=timezone.now()+timedelta(minutes=1))
        self.assertEqual(self.client.post('/api/ai/cancel',json.dumps({'thread_id':own.pk}),
            content_type='application/json').status_code,200)
        lease.refresh_from_db(); self.assertTrue(lease.cancel_requested)
        self.assertEqual(self.client.post('/api/ai/cancel',json.dumps({'thread_id':foreign.pk}),
            content_type='application/json').status_code,403)
        self.assertEqual([item['id'] for item in self.client.get('/api/ai/conversations').json()['conversations']], [own.pk])
        messages = [SimpleNamespace(type='human',content='Question'), SimpleNamespace(type='ai',content='Answer'),
            SimpleNamespace(type='tool',content=json.dumps({'files':[{'name':'result.csv','url':'/media/old','size':3}]}))]
        saver=Mock(); saver.get_tuple.return_value=SimpleNamespace(checkpoint={'channel_values':{'messages':messages}})
        with patch('core.ai_agent._checkpoint_saver',return_value=saver):
            turn=self.client.get('/api/ai/conversations',{'thread_id':own.pk}).json()['turns'][0]
        self.assertEqual(turn['answer'],'Answer')
        self.assertEqual(turn['files'][0]['url'],f'/ai/files/{own.pk}/result.csv')

    def test_executor_mounts_only_staged_inputs_and_rejects_bad_outputs(self):
        from .ai_executor import execute
        with tempfile.TemporaryDirectory(dir=settings.BASE_DIR) as tmp, override_settings(AI_EXECUTOR_IMAGE='fixture:local'):
            root=Path(tmp)/'workspace'; root.mkdir(); (root/'data.csv').write_text('x\n1\n')
            (root/'not-input.py').write_text('secret_fixture')
            envelope={'exit_code':0,'stdout':'done','files':[None, {'name':'../escape.csv','data':''},
                {'name':'bad.py','data':''},{'name':'result.csv','data':base64.b64encode(b'x\n2\n').decode()}]}
            calls=[]
            def launch(command,stdout,stderr):
                calls.append(command)
                mount=next(part for part in command if part.startswith('type=bind,'))
                staged=Path(mount.split('src=',1)[1].split(',dst=',1)[0])
                self.assertEqual({p.name for p in staged.iterdir()},{'data.csv'})
                stdout.write(json.dumps(envelope).encode());stdout.flush()
                return Mock(poll=Mock(return_value=0),returncode=0)
            with patch('core.ai_executor.tempfile.tempdir',tmp),patch('core.ai_executor.subprocess.Popen',side_effect=launch), \
                    patch('core.ai_executor.subprocess.run'):
                result=execute("print('done')",root)
            command=calls[0]
            for flag in ('--network=none','--read-only','--cap-drop=ALL','--user=65534:65534','--memory=512m'):
                self.assertIn(flag,command)
            self.assertEqual(result['files'],[{'name':'result.csv','size':4}])
            self.assertEqual((root/'result.csv').read_text(),'x\n2\n')
            self.assertFalse((Path(tmp)/'escape.csv').exists())

    def test_executor_cancellation_removes_container(self):
        from .ai_executor import execute
        stopped=Mock();stopped.is_set.side_effect=[False, True, True];stopped.wait.return_value=True
        proc=Mock();proc.poll.return_value=None
        with tempfile.TemporaryDirectory(dir=settings.BASE_DIR) as tmp, override_settings(AI_EXECUTOR_IMAGE='fixture:local'), \
                patch('core.ai_executor.tempfile.tempdir',tmp),patch('core.ai_executor.subprocess.Popen',return_value=proc), \
                patch('core.ai_executor.subprocess.run') as remove:
            result=execute('while True: pass',tmp,stopped)
        self.assertIn('停止',result['error']);proc.kill.assert_called_once()
        self.assertEqual(remove.call_args.args[0][1:3],['rm','-f'])

    def test_worker_identity_collision_does_not_credit_another_person(self):
        from .role_utils import resolve_or_create_worker
        other=User.objects.create_user('original-worker')
        original=Worker.objects.create(user=other,employee_id=self.user.username,full_name='Original')
        resolved,created=resolve_or_create_worker(self.user)
        self.assertTrue(created);self.assertEqual(resolved.user_id,self.user.pk)
        self.assertNotEqual(resolved.pk,original.pk)
        self.assertEqual(resolve_or_create_worker(self.user)[0].pk,resolved.pk)

    def test_approval_records_manager_without_preexisting_worker(self):
        from .models import WaterRequest, Zone
        zone=Zone.objects.create(code='APPROVAL-FIXTURE',name='Approval fixture')
        req=WaterRequest.objects.create(zone=zone,submitter_user=self.user,
            start_datetime=timezone.now(),end_datetime=timezone.now()+timedelta(hours=1))
        response=self.client.post(f'/requests/{req.pk}/update/',{'status':'info_needed'})
        self.assertEqual(response.status_code,200)
        req.refresh_from_db();self.assertEqual(req.approver.user_id,self.user.pk)
        self.assertIsNotNone(req.processed_at)

    def test_registration_approval_flag_does_not_block_other_management_tabs(self):
        from .models import ManagerProfile,RegistrationRequest
        from .registration_service import approve,reject
        manager=User.objects.create_user('limited-approver')
        ManagerProfile.objects.create(user=manager,employee_id='LIMITED-APPROVER',full_name='Fixture',can_approve_registrations=False)
        self.client.force_login(manager)
        self.assertEqual(self.client.get('/user-management/').status_code,200)
        reg=RegistrationRequest.objects.create(username='approved-fixture',full_name='Fixture',phone='000',requested_role='field_worker',password='fixture')
        self.assertEqual(self.client.post('/user-management/',{'action':'approve','request_id':reg.pk}).status_code,403)
        reg.refresh_from_db();self.assertEqual(reg.status,'pending')
        manager.is_staff=True;manager.save(update_fields=['is_staff'])
        approve(reg.pk,manager)
        with self.assertRaises(ValueError):reject(reg.pk,manager)
        reg.refresh_from_db();self.assertEqual(reg.status,'approved')

    def test_disabling_account_rotates_tokens_and_invalidates_session(self):
        from .session_guard import set_account_enabled
        from .models import ManagerProfile
        worker=Worker.objects.create(user=self.user,employee_id='DISABLE-FIXTURE',full_name='Fixture')
        manager=ManagerProfile.objects.create(user=self.user,employee_id='DISABLE-MANAGER',full_name='Fixture')
        old_worker,old_manager=worker.api_token,manager.api_token
        set_account_enabled(self.user,False)
        worker.refresh_from_db();manager.refresh_from_db()
        self.assertFalse(worker.active);self.assertFalse(manager.active)
        self.assertNotEqual(worker.api_token,old_worker);self.assertNotEqual(manager.api_token,old_manager)
        response=self.client.get('/requests/',HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code,401)

    def test_import_fallback_resolves_site_internal_key_and_keeps_name_prefix(self):
        module='core.management.commands.import_maxicom_mdb_linux'
        ccu2,_=Patch.objects.get_or_create(code='CCU2',defaults={'name':'Two'})
        ccu44,_=Patch.objects.get_or_create(code='CCU44',defaults={'name':'Forty-four'})
        ccu7,_=Patch.objects.get_or_create(code='CCU7',defaults={'name':'Seven'})
        old=Patch.objects.create(code='station-901',name='Old',mdb_index=901,parent=ccu2,controller_number=999,controller_channel=1)
        tables={
            'SITE_CF':[{'IndexNumber':'2','SiteNumber':'44'},{'IndexNumber':'44','SiteNumber':'2'}],
            'CTROL_CF':[{'IndexNumber':'501','IndexName':'SAT1','ControllerSiteNumber':'2'},
                {'IndexNumber':'502','IndexName':'SAT 7-1','ControllerSiteNumber':'44'}],
            'STATN_CF':[{'IndexNumber':'901','StationSiteNumber':'2','StationControllerNumber':'501','StationControllerChannel':'19'},
                {'IndexNumber':'902','StationSiteNumber':'44','StationControllerNumber':'502','StationControllerChannel':'20'}],
            'XA_LOG':[{'SignalType':'M','SignalTable':'S','XactIndex':'901','XactStamp':'20261025100000','SignalValue':'20'}],
        }
        with patch(module+'._mdb_rows',side_effect=lambda _path,table:iter(tables[table])), \
                patch(module+'.os.path.exists',return_value=True),patch(module+'.Command._import_flow'):
            call_command('import_maxicom_mdb_linux',mdb='fixture.mdb',stdout=io.StringIO())
        old.refresh_from_db();self.assertEqual(old.parent_id,ccu44.pk)
        self.assertEqual(old.controller_channel,19);self.assertEqual(old.controller_number,501)
        self.assertEqual(Patch.objects.get(code='station-902').parent_id,ccu7.pk)
