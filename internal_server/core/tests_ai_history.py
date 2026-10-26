import io
import json
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timedelta, timezone as utc
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from .ai_history import day_bounds, prune_history
from .ai_storage import conversation_for, ConversationExpired, workspace
from .models import AIConversation, AIExecutionLease, AISettings


class DailyAIHistoryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.directory=tempfile.TemporaryDirectory(dir=settings.BASE_DIR)
        self.override=override_settings(AI_PRIVATE_ROOT=self.directory.name)
        self.override.enable()
        self.addCleanup(self.directory.cleanup);self.addCleanup(self.override.disable)
        self.now=datetime(2026,10,26,16,0,tzinfo=utc.utc)  # Shanghai October 27 00:00.
        self.user=User.objects.create_user('daily-ai',is_staff=True)
        self.old=AIConversation.objects.create(id=f'u{self.user.pk}-abcdef12',owner=self.user,title='Yesterday')
        self.today=AIConversation.objects.create(id=f'u{self.user.pk}-abcdef34',owner=self.user,title='Today')
        AIConversation.objects.filter(pk=self.old.pk).update(created_at=self.now-timedelta(seconds=1),updated_at=self.now)
        AIConversation.objects.filter(pk=self.today.pk).update(created_at=self.now,updated_at=self.now)
        self.client.force_login(self.user)
        self.database=Path(self.directory.name)/'checkpoints.sqlite3'
        with closing(sqlite3.connect(self.database)) as db, db:
            db.executescript('CREATE TABLE checkpoints(thread_id TEXT,type TEXT,checkpoint BLOB,checkpoint_id TEXT);CREATE TABLE writes(thread_id TEXT,value TEXT);')
            for item in (self.old,self.today):
                db.execute('INSERT INTO checkpoints VALUES(?,?,?,?)',(item.pk,'json',b'{}','1'))
                db.execute('INSERT INTO writes VALUES(?,?)',(item.pk,'fixture'))
                (workspace(item.pk)/'report.xlsx').write_bytes(b'fixture')

    def test_shanghai_calendar_cutoff_is_independent_of_host_timezone(self):
        with override_settings(TIME_ZONE='UTC'):
            self.assertEqual(day_bounds(self.now)[0].isoformat(),'2026-10-27T00:00:00+08:00')
            self.assertEqual(day_bounds(self.now-timedelta(seconds=1))[0].date().isoformat(),'2026-10-26')

    def test_old_history_checkpoint_writes_and_attachments_are_deleted_together(self):
        result=prune_history(now=self.now)
        self.assertEqual(result['removed'],1)
        self.assertFalse(AIConversation.objects.filter(pk=self.old.pk).exists())
        self.assertTrue(AIConversation.objects.filter(pk=self.today.pk).exists())
        self.assertFalse((Path(self.directory.name)/'workspaces'/self.old.pk).exists())
        self.assertTrue((Path(self.directory.name)/'workspaces'/self.today.pk/'report.xlsx').exists())
        with closing(sqlite3.connect(self.database)) as db, db:
            self.assertEqual(db.execute('SELECT thread_id FROM checkpoints').fetchall(),[(self.today.pk,)])
            self.assertEqual(db.execute('SELECT thread_id FROM writes').fetchall(),[(self.today.pk,)])
        self.assertEqual(prune_history(now=self.now)['removed'],0)

    def test_dry_run_preserves_rows_messages_and_files(self):
        with patch('core.ai_history.timezone.now',return_value=self.now):
            output=io.StringIO();call_command('prune_ai_history',dry_run=True,stdout=output)
        self.assertEqual(json.loads(output.getvalue())['removed'],1)
        self.assertEqual(AIConversation.objects.count(),2)
        self.assertTrue((Path(self.directory.name)/'workspaces'/self.old.pk/'report.xlsx').exists())

    def test_active_expired_task_is_cancelled_and_removed_only_after_lease_finishes(self):
        lease=AIExecutionLease.objects.create(conversation=self.old,owner=self.user,expires_at=self.now+timedelta(minutes=2))
        self.assertEqual(prune_history(now=self.now)['active_deferred'],1)
        lease.refresh_from_db();self.assertTrue(lease.cancel_requested)
        self.assertTrue(AIConversation.objects.filter(pk=self.old.pk).exists())
        lease.delete();self.assertEqual(prune_history(now=self.now)['removed'],1)

    def test_expired_detail_and_download_are_inaccessible_before_cleanup(self):
        with patch('core.ai_history.timezone.now',return_value=self.now),patch('core.ai_views.maybe_prune_history'):
            response=self.client.get('/api/ai/conversations')
            self.assertEqual([x['id'] for x in response.json()['conversations']],[self.today.pk])
            self.assertEqual(response.json()['day'],'2026-10-27')
            self.assertEqual(self.client.get('/api/ai/conversations',{'thread_id':self.old.pk}).status_code,404)
            self.assertEqual(self.client.get(f'/ai/files/{self.old.pk}/report.xlsx').status_code,404)
            with self.assertRaises(ConversationExpired):conversation_for(self.user,f'u{self.user.pk}-ffffffff')
        self.assertEqual(AIConversation.objects.count(),2)

    def test_cross_day_send_uses_new_thread_and_retains_the_submitted_question(self):
        AISettings.objects.update_or_create(pk=1,defaults={'enabled':True,'api_base_url':'https://fixture.invalid','api_key':'fixture','model_name':'fixture'})
        with patch('core.ai_history.timezone.now',return_value=self.now), \
                patch('core.ai_views.maybe_prune_history'),patch('core.ai_views._stream_via_queue',return_value=iter(())):
            response=self.client.post('/api/ai/chat',json.dumps({'thread_id':self.old.pk,'message':'New day question'}),content_type='application/json')
            events=b''.join(response.streaming_content).decode()
            response.close()
        first=json.loads(events.split('data: ',1)[1].split('\n\n')[0])
        self.assertTrue(first['reset']);self.assertNotEqual(first['thread_id'],self.old.pk)
        self.assertEqual(AIConversation.objects.get(pk=first['thread_id']).title,'New day question')

    def test_legacy_registration_date_is_reconciled_from_original_checkpoint(self):
        from langgraph.checkpoint.sqlite import SqliteSaver
        with closing(sqlite3.connect(self.database)) as db, db:
            serializer=SqliteSaver(db).serde
            kind,data=serializer.dumps_typed({'ts':(self.now-timedelta(days=2)).isoformat()})
            db.execute('UPDATE checkpoints SET type=?,checkpoint=? WHERE thread_id=?',(kind,data,self.today.pk))
            # Avoid decoding the intentionally minimal other checkpoint.
            db.execute('DELETE FROM checkpoints WHERE thread_id=?',(self.old.pk,))
        result=prune_history(now=self.now,reconcile_dates=True)
        self.assertEqual(result['dates_reconciled'],1)
        self.assertFalse(AIConversation.objects.exists())
