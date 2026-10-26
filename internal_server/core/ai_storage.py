"""AI state is private. Downloads require a registered owned conversation."""
import os
import re
from pathlib import Path

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.http import FileResponse, Http404
from django.utils import timezone

from .models import AIConversation
from .role_utils import get_django_user, get_user_role, ROLE_MANAGER, ROLE_SUPER_ADMIN

THREAD_RE = re.compile(r'u[0-9]+-[0-9a-f]{8,32}\Z')


class ConversationExpired(Http404):
    pass


def private_root():
    root = Path(getattr(settings, 'AI_PRIVATE_ROOT', settings.BASE_DIR / 'private_ai'))
    from django.core.exceptions import ImproperlyConfigured
    for public in (settings.MEDIA_ROOT, settings.STATIC_ROOT):
        if public and root.resolve().is_relative_to(Path(public).resolve()):
            raise ImproperlyConfigured('AI_PRIVATE_ROOT must be outside media/static directories')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root.resolve()


def workspace(thread_id):
    if not THREAD_RE.fullmatch(thread_id):
        raise ValueError('invalid thread_id')
    root = private_root() / 'workspaces'
    root.mkdir(mode=0o700, exist_ok=True)
    path = root / thread_id
    if path.is_symlink():
        raise PermissionDenied
    path.mkdir(mode=0o700, exist_ok=True)
    return path


def conversation_for(user, thread_id, *, create=False, title='', allow_expired=False):
    owner = get_django_user(user)
    if not owner or get_user_role(user) not in (ROLE_MANAGER, ROLE_SUPER_ADMIN):
        raise PermissionDenied('无权限使用 AI 助手')
    if not THREAD_RE.fullmatch(thread_id) or not thread_id.startswith(f'u{owner.pk}-'):
        raise PermissionDenied('无权访问此会话')
    if create:
        item, _ = AIConversation.objects.get_or_create(id=thread_id, defaults={'owner': owner, 'title': title[:120]})
    else:
        item = AIConversation.objects.filter(pk=thread_id).first()
        if item is None:
            raise ConversationExpired('会话已过期，请开启新对话')
    if item.owner_id != owner.pk:
        raise PermissionDenied('无权访问此会话')
    from .ai_history import day_bounds
    start, end = day_bounds()
    if not allow_expired and not start <= item.created_at < end:
        raise ConversationExpired('会话已过期，请开启新对话')
    return item


def download(request, thread_id, name):
    conversation_for(request.user, thread_id)
    if Path(name).name != name or name.startswith('.'):
        raise Http404
    path = workspace(thread_id) / name
    if path.is_symlink() or not path.is_file() or path.suffix.lower() not in {'.xlsx', '.xls', '.csv', '.json', '.txt', '.docx', '.pdf', '.png', '.jpg', '.svg'}:
        raise Http404
    response = FileResponse(path.open('rb'), as_attachment=True, filename=name)
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def artifact_url(thread_id, name):
    from django.urls import reverse
    return reverse('core:ai_artifact', kwargs={'thread_id': thread_id, 'name': name})


def media_file(request, path, document_root=None):
    from django.views.static import serve
    # Deny private/legacy AI state before reaching Django's filesystem server.
    normalized = path.replace('\\', '/').lower()
    if any(p.startswith('.') for p in normalized.split('/')) or normalized.split('/')[0].startswith('ai_'):
        raise Http404
    if Path(path).suffix.lower() in {'.sqlite3', '.sqlite', '.db', '.mdb', '.zip', '.py', '.env'}:
        raise Http404
    response = serve(request, path, document_root=document_root or settings.MEDIA_ROOT)
    response['Cache-Control'] = 'private, no-store'
    return response
