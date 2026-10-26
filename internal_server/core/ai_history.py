"""Calendar-day AI retention. Business records and emailed files are unaffected."""
from datetime import datetime, time, timedelta
import logging
import shutil
import sqlite3
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.utils import timezone

from .models import AIConversation, AIExecutionLease

logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo('Asia/Shanghai')


def day_bounds(now=None):
    now = now or timezone.now()
    day = now.astimezone(SHANGHAI).date()
    start = datetime.combine(day, time.min, tzinfo=SHANGHAI)
    return start, start + timedelta(days=1)


def policy():
    now = timezone.now()
    start, end = day_bounds(now)
    return {'day': start.date().isoformat(), 'server_now': now.isoformat(), 'expires_at': end.isoformat()}


def _remove_workspace(root, thread_id):
    from .ai_storage import THREAD_RE
    if not THREAD_RE.fullmatch(thread_id):
        raise ValueError('Invalid AI workspace identifier')
    parent = root / 'workspaces'
    if parent.is_symlink() or parent.resolve().parent != root.resolve():
        raise ValueError('AI workspace root outside private storage')
    parent = parent.resolve()
    path = parent / thread_id
    if path.is_symlink():
        path.unlink()
        return
    if path.exists():
        # Verify the final absolute deletion target, including on Windows.
        if path.resolve().parent != parent or path.resolve().name != thread_id:
            raise ValueError('AI workspace outside retention directory')
        shutil.rmtree(path)


def prune_history(*, now=None, dry_run=False, reconcile_dates=False):
    from .ai_storage import private_root
    now = now or timezone.now()
    start, _ = day_bounds(now)
    root = private_root()
    database = root / 'checkpoints.sqlite3'
    if database.is_symlink():
        raise ValueError('Checkpoint database must not be a symlink')
    connection = sqlite3.connect(database.as_uri() + '?mode=rw', uri=True, timeout=5) if database.exists() else None
    try:
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")} if connection else set()
        reconciled = 0
        legacy_expired = set()
        if reconcile_dates and 'checkpoints' in tables:
            # Legacy migration registered old threads with the migration date.
            # Restore the original conversation day from its first checkpoint.
            from langgraph.checkpoint.sqlite import SqliteSaver
            serializer = SqliteSaver(connection).serde
            for conversation in AIConversation.objects.all().iterator():
                row = connection.execute('SELECT type, checkpoint FROM checkpoints WHERE thread_id=? '
                    'ORDER BY checkpoint_id LIMIT 1', (conversation.pk,)).fetchone()
                if not row:
                    continue
                checkpoint = serializer.loads_typed(row)
                first = datetime.fromisoformat(checkpoint['ts'])
                if first < conversation.created_at:
                    reconciled += 1
                    if first < start:
                        legacy_expired.add(conversation.pk)
                    if not dry_run:
                        AIConversation.objects.filter(pk=conversation.pk).update(created_at=first)
        expired = AIConversation.objects.filter(created_at__lt=start)
        ids = sorted(set(expired.values_list('pk', flat=True)) | legacy_expired)
        active = set(AIExecutionLease.objects.filter(conversation_id__in=ids, expires_at__gt=now)
                     .values_list('conversation_id', flat=True))
        if not dry_run:
            AIExecutionLease.objects.filter(conversation_id__in=active).update(cancel_requested=True)
        removed = 0
        for thread_id in ids:
            if thread_id in active:
                continue
            if not dry_run:
                if connection:
                    with connection:
                        for table in ('checkpoints', 'writes'):
                            if table in tables:
                                connection.execute(f'DELETE FROM {table} WHERE thread_id=?', (thread_id,))
                _remove_workspace(root, thread_id)
                AIConversation.objects.filter(pk=thread_id, created_at__lt=start).delete()
            removed += 1
        return {'day': start.date().isoformat(), 'expired': len(ids), 'removed': removed,
                'active_deferred': len(active), 'dates_reconciled': reconciled, 'dry_run': dry_run}
    finally:
        if connection:
            connection.close()


def maybe_prune_history():
    key = 'ai-history-prune-' + day_bounds()[0].date().isoformat()
    if cache.add(key, True, timeout=60):
        try:
            prune_history()
        except Exception:
            cache.delete(key)
            logger.exception('AI daily-history cleanup failed; expired history remains inaccessible')
