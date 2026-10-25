"""SSE endpoint for the AI data-analyst agent.

Streams agent output (LLM tokens + tool-call progress) to the browser as
Server-Sent Events. The agent runs server-side and calls ORM @tools directly.

Streaming design: the LangChain agent is async, but Django's StreamingHttpResponse
consumes a sync generator. We run the async agent on a dedicated event loop in a
worker thread, pushing each SSE event onto a thread-safe queue that the sync
generator drains — so tokens reach the browser incrementally instead of buffered.
"""
import json
import logging
import queue
import re
import threading
import uuid
import time
from datetime import timedelta
from django.db import transaction, IntegrityError, close_old_connections
from django.utils import timezone
from core.ai_storage import conversation_for
from core.models import AIConversation, AIExecutionLease

from django.contrib.auth.decorators import login_required
from django.http import StreamingHttpResponse, HttpResponseBadRequest, JsonResponse
from django.views.decorators.http import require_POST

from core.models import AISettings
from core.role_utils import get_user_role, ROLE_SUPER_ADMIN, ROLE_MANAGER

logger = logging.getLogger(__name__)

# Roles allowed to use the AI assistant. Only managers and super-admins.
_ALLOWED_ROLES = {ROLE_SUPER_ADMIN, ROLE_MANAGER}


def _sse(event_type: str, data: dict) -> str:
    """Format one Server-Sent Event frame."""
    return f"data: {json.dumps({'event': event_type, **data}, ensure_ascii=False)}\n\n"


@login_required(login_url='core:login')
def ai_status(request):
    """GET -> whether the AI assistant is available to the current user.

    Returns {"available": bool}. The frontend uses this to decide whether to
    show the 🤖 launcher button. A user sees the button only when:
      - they are a manager or super-admin (role), AND
      - the feature is enabled AND fully configured (base_url/key/model) in admin.
    """
    role = get_user_role(request.user)
    cfg = AISettings.get_settings()
    configured = bool(cfg.enabled and cfg.api_base_url and cfg.api_key and cfg.model_name)
    available = role in _ALLOWED_ROLES and configured
    return JsonResponse({'available': available})


@login_required(login_url='core:login')
@require_POST
def ai_chat(request):
    role = get_user_role(request.user)
    if role not in _ALLOWED_ROLES:
        return JsonResponse({'error': '无权限使用 AI 助手'}, status=403)
    cfg = AISettings.get_settings()
    if not (cfg.enabled and cfg.api_base_url and cfg.api_key and cfg.model_name):
        return JsonResponse({'error': 'AI 助手尚未配置，请联系管理员'}, status=400)
    try:
        body = json.loads(request.body)
        message = body.get('message', '')
        if not isinstance(message, str) or not message.strip() or len(message) > 20000:
            raise ValueError('请输入不超过 20000 字的消息')
        supplied = body.get('thread_id')
        if supplied and not isinstance(supplied, str):
            raise ValueError('会话编号无效')
        thread_id = supplied or f'u{request.user.pk}-{uuid.uuid4().hex}'
        conversation = conversation_for(request.user, thread_id, create=not supplied, title=message.strip())
    except (ValueError, AttributeError, TypeError):
        return JsonResponse({'error': '消息或会话格式无效'}, status=400)
    try:
        with transaction.atomic():
            AIExecutionLease.objects.filter(owner=request.user, expires_at__lte=timezone.now()).delete()
            lease = AIExecutionLease.objects.create(conversation=conversation, owner=request.user,
                expires_at=timezone.now()+timedelta(seconds=300))
            if AIExecutionLease.objects.filter(expires_at__gt=timezone.now()).count() > 3:
                raise ValueError('分析任务较多，请稍后重试')
    except IntegrityError:
        return JsonResponse({'error': '上一项 AI 任务仍在运行或停止中，请稍候再试'}, status=409)
    except ValueError as exc:
        return JsonResponse({'error':str(exc)},status=429)
    started = [False]
    def release_or_cancel():
        qs=AIExecutionLease.objects.filter(conversation_id=thread_id, token=lease.token)
        if started[0]:qs.update(cancel_requested=True)
        else:qs.delete()
    def event_stream():
        try:
            yield _sse('thread', {'thread_id': thread_id})
            started[0] = True
            yield from _stream_via_queue(message.strip(), thread_id)
        finally:
            release_or_cancel()
    resp = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    resp._resource_closers.append(release_or_cancel)
    resp['Cache-Control'] = 'private, no-store'
    resp['X-Accel-Buffering'] = 'no'
    resp['Content-Encoding'] = 'identity'
    return resp


def _stream_via_queue(message: str, thread_id: str):
    q = queue.Queue(maxsize=128)
    stopped = threading.Event()
    sentinel = object()
    lease = AIExecutionLease.objects.get(conversation_id=thread_id)
    def put(event):
        while not stopped.is_set():
            try:
                q.put(event, timeout=0.25)
                return
            except queue.Full:
                continue
    def worker():
        close_old_connections()
        try:
            from core.ai_agent import build_agent, ensure_workspace
            from langchain_core.messages import HumanMessage
            ensure_workspace(thread_id, refresh=True)
            put(('snapshot', {'at': timezone.localtime().isoformat()}))
            agent = build_agent()
            config = {'configurable': {'thread_id': thread_id}, 'recursion_limit': 30}
            context = {'thread_id': thread_id, 'cancel_event': stopped}
            seen = {}
            stream = agent.stream({'messages': [HumanMessage(content=message)]}, config=config,
                context=context, stream_mode='messages')
            try:
                for chunk, metadata in stream:
                    if stopped.is_set():
                        break
                    for evt in _events_from_chunk(chunk, seen):
                        put(evt)
            finally:
                stream.close()
            AIConversation.objects.filter(pk=thread_id).update(updated_at=timezone.now())
        except Exception:
            logger.exception('AI agent task failed')
            put(('error', {'message': '分析未完成，请稍后重试；已生成的文件仍可下载。'}))
        finally:
            AIExecutionLease.objects.filter(conversation_id=thread_id, token=lease.token).delete()
            put(sentinel)
            close_old_connections()
    threading.Thread(target=worker, daemon=True).start()
    deadline = time.monotonic() + 180
    next_cancel_check = 0
    try:
        while time.monotonic() < deadline:
            try:
                item = q.get(timeout=3)
            except queue.Empty:
                item = None
            cancelled = False
            if time.monotonic() >= next_cancel_check:
                cancelled = AIExecutionLease.objects.filter(conversation_id=thread_id, token=lease.token, cancel_requested=True).exists()
                next_cancel_check = time.monotonic() + 3
            if cancelled:
                yield _sse('error', {'message': '任务已停止'})
                return
            if item is sentinel:
                yield _sse('done', {})
                return
            if item is None:
                yield ': heartbeat\n\n'
            else:
                yield _sse(*item)
        yield _sse('error', {'message': '分析达到时间限制，请缩小范围后重试'})
    finally:
        stopped.set()


def _events_from_chunk(chunk, seen_tool_calls):
    """Translate one streamed message chunk into zero or more (event_type, payload) tuples."""
    from langchain_core.messages import AIMessageChunk, ToolMessage
    # Tool call requests arrive as AIMessageChunks carrying tool_call_chunks
    if getattr(chunk, 'tool_call_chunks', None):
        for tc in chunk.tool_call_chunks:
            name = tc.get('name')
            idx = tc.get('index', 0)
            call_id = tc.get('id')
            # Tool indices restart at zero on each model turn. Prefer the
            # actual call ID so later rounds and parallel same-name tools
            # remain distinct in the client timeline.
            message_id = (getattr(chunk, 'id', None), seen_tool_calls.get('_round', 0))
            key = ('id', call_id) if call_id else ('index', message_id, idx)
            if name and key not in seen_tool_calls:
                seen_tool_calls[key] = name
                seen_tool_calls[('index', message_id, idx)] = name
                args_str = tc.get('args', '') if isinstance(tc.get('args'), str) else ''
                try:
                    parsed_args = json.loads(args_str) if args_str else {}
                except json.JSONDecodeError:
                    parsed_args = {'_raw': args_str}
                yield ('tool_start', {'id': call_id, 'name': name, 'args': parsed_args})
    # Tool results arrive as ToolMessage
    if isinstance(chunk, ToolMessage):
        name = getattr(chunk, 'name', 'tool')
        call_id = getattr(chunk, 'tool_call_id', None)
        content = getattr(chunk, 'content', '')
        if isinstance(content, list):
            content = json.dumps(content, ensure_ascii=False)
        # run_python_code returns JSON with a `files` list, export_work_reports_excel
        # returns a single `file` object — emit one `file` event per generated
        # artifact so the UI shows a download card.
        try:
            parsed = json.loads(content) if isinstance(content, str) else (content or {})
        except (json.JSONDecodeError, TypeError):
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}
        generated = parsed.get('files', []) if name == 'run_python_code' else []
        if not isinstance(generated, list):
            generated = []
        if isinstance(parsed.get('file'), dict):
            generated = [*generated, parsed['file']]
        for finfo in generated:
            if not isinstance(finfo, dict):
                continue
            yield ('file', {
                'name': finfo.get('name', ''),
                'url': finfo.get('url', ''),
                'size': finfo.get('size', 0),
            })
        out_preview = str(content)[:800]
        failed = (getattr(chunk, 'status', None) == 'error' or bool(parsed.get('error'))
                  or parsed.get('success') is False or parsed.get('exit_code', 0) not in (0, None))
        yield ('tool_end', {'id': call_id, 'name': name, 'status': 'error' if failed else 'done', 'output': out_preview})
        seen_tool_calls['_round'] = seen_tool_calls.get('_round', 0) + 1
        return
    # Regular AI text tokens (streamed as AIMessageChunk; note .type is the
    # class name 'AIMessageChunk', not 'ai', so use isinstance).
    if isinstance(chunk, AIMessageChunk):
        text = chunk.text if hasattr(chunk, 'text') else ''
        if text:
            yield ('token', {'text': text})


@login_required(login_url='core:login')
@require_POST
def ai_cancel(request):
    try:
        body = json.loads(request.body)
        conversation = conversation_for(request.user, body.get('thread_id', ''))
    except (ValueError, TypeError, AttributeError):
        return JsonResponse({'error': '会话格式无效'}, status=400)
    AIExecutionLease.objects.filter(conversation=conversation, owner=request.user).update(cancel_requested=True)
    return JsonResponse({'success': True})


@login_required(login_url='core:login')
def ai_conversations(request):
    if get_user_role(request.user) not in _ALLOWED_ROLES:
        return JsonResponse({'error': '无权限'}, status=403)
    from core.ai_agent import _checkpoint_saver
    thread_id = request.GET.get('thread_id')
    if not thread_id:
        return JsonResponse({'conversations': list(AIConversation.objects.filter(owner=request.user)
            .order_by('-updated_at').values('id', 'title', 'updated_at')[:30])})
    conversation_for(request.user, thread_id)
    checkpoint = _checkpoint_saver().get_tuple({'configurable': {'thread_id': thread_id}})
    messages = checkpoint.checkpoint.get('channel_values', {}).get('messages', []) if checkpoint else []
    turns = []
    current = None
    for message in messages[-100:]:
        role = getattr(message, 'type', '')
        content = getattr(message, 'content', '')
        if role == 'human':
            current={'question':content[:30000] if isinstance(content,str) else '', 'answer':'', 'files':[]}
            turns.append(current)
        elif current is not None and role == 'ai' and isinstance(content,str):
            current['answer']=(current['answer']+content)[:60000]
        elif current is not None and role == 'tool':
            try:
                data=json.loads(content) if isinstance(content,str) else {}
                files=data.get('files',[])
                if isinstance(data.get('file'),dict):files=[*files,data['file']]
                from .ai_storage import artifact_url
                from pathlib import Path
                for file in files[:20]:
                    name=file.get('name','')
                    if name and Path(name).name==name:
                        current['files'].append({'name':name,'size':file.get('size',0),'url':artifact_url(thread_id,name)})
            except (ValueError,TypeError,AttributeError):
                continue
    return JsonResponse({'thread_id': thread_id, 'turns': turns})
