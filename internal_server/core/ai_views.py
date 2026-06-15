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
import threading
import uuid

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
    """POST {message, thread_id?} -> SSE stream of agent output.

    Events emitted (each under a ``data:`` line):
      {"event":"thread","thread_id":"..."}      the conversation thread id
      {"event":"tool_start","name":"...","args":{...}}   tool invoked
      {"event":"token","text":"..."}            streamed LLM token
      {"event":"tool_end","name":"...","output":"..."}   tool finished
      {"event":"done"}                          stream complete
      {"event":"error","message":"..."}         failure
    """
    role = get_user_role(request.user)
    if role not in _ALLOWED_ROLES:
        return JsonResponse({'error': '无权限使用 AI 助手'}, status=403)

    cfg = AISettings.get_settings()
    if not (cfg.enabled and cfg.api_base_url and cfg.api_key and cfg.model_name):
        return JsonResponse({'error': 'AI 助手未配置，请联系管理员在后台设置 base_url / api_key / model'}, status=400)

    try:
        body = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return HttpResponseBadRequest('invalid json')
    message = (body.get('message') or '').strip()
    if not message:
        return HttpResponseBadRequest('message is required')
    # Per-user conversation thread. New id if the client didn't supply one.
    thread_id = body.get('thread_id') or f'u{request.user.id}-{uuid.uuid4().hex[:8]}'

    def event_stream():
        # Echo the thread id first so the client can store it for follow-ups.
        yield _sse('thread', {'thread_id': thread_id})
        yield from _stream_via_queue(message, thread_id)

    resp = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    resp['Cache-Control'] = 'no-cache'
    resp['X-Accel-Buffering'] = 'no'  # disable proxy buffering for true streaming
    return resp


def _stream_via_queue(message: str, thread_id: str):
    """Sync generator: run the agent (sync stream) on a worker thread, yield SSE frames.

    The worker thread is a plain Python thread (no event loop), so the @tool
    functions can call the Django ORM synchronously without hitting the
    "You cannot call this from an async context" error.
    """
    q: "queue.Queue" = queue.Queue()
    _SENTINEL = object()

    def worker():
        from core.ai_agent import build_agent, set_current_thread
        from langchain_core.messages import HumanMessage
        try:
            set_current_thread(thread_id)
            agent = build_agent()
            config = {'configurable': {'thread_id': thread_id}}
            input_msg = {'messages': [HumanMessage(content=message)]}
            seen_tool_calls = {}
            # Sync stream — runs tools in this thread, where Django ORM is safe.
            for chunk, metadata in agent.stream(
                input_msg, config=config, stream_mode='messages'
            ):
                for evt in _events_from_chunk(chunk, seen_tool_calls):
                    q.put(evt)
        except Exception as e:  # noqa: BLE001
            logger.exception('AI agent worker failed')
            q.put(('error', {'message': f'agent error: {e}'}))
        finally:
            q.put(_SENTINEL)

    threading.Thread(target=worker, daemon=True).start()

    while True:
        item = q.get()
        if item is _SENTINEL:
            break
        event_type, payload = item
        yield _sse(event_type, payload)
    yield _sse('done', {})


def _events_from_chunk(chunk, seen_tool_calls):
    """Translate one streamed message chunk into zero or more (event_type, payload) tuples."""
    from langchain_core.messages import AIMessageChunk, ToolMessage
    # Tool call requests arrive as AIMessageChunks carrying tool_call_chunks
    if getattr(chunk, 'tool_call_chunks', None):
        for tc in chunk.tool_call_chunks:
            name = tc.get('name')
            idx = tc.get('index', 0)
            if name and idx not in seen_tool_calls:
                seen_tool_calls[idx] = name
                args_str = tc.get('args', '') if isinstance(tc.get('args'), str) else ''
                try:
                    parsed_args = json.loads(args_str) if args_str else {}
                except json.JSONDecodeError:
                    parsed_args = {'_raw': args_str}
                yield ('tool_start', {'name': name, 'args': parsed_args})
        return
    # Tool results arrive as ToolMessage
    if isinstance(chunk, ToolMessage):
        name = getattr(chunk, 'name', 'tool')
        content = getattr(chunk, 'content', '')
        if isinstance(content, list):
            content = json.dumps(content, ensure_ascii=False)
        # run_python_code returns JSON with a `files` list — emit one
        # `file` event per generated artifact so the UI shows a download card.
        if name == 'run_python_code':
            try:
                parsed = json.loads(content) if isinstance(content, str) else (content or {})
                for finfo in parsed.get('files', []):
                    yield ('file', {
                        'name': finfo.get('name', ''),
                        'url': finfo.get('url', ''),
                        'size': finfo.get('size', 0),
                    })
            except (json.JSONDecodeError, AttributeError, TypeError):
                pass
        out_preview = str(content)[:800]
        yield ('tool_end', {'name': name, 'output': out_preview})
        return
    # Regular AI text tokens (streamed as AIMessageChunk; note .type is the
    # class name 'AIMessageChunk', not 'ai', so use isinstance).
    if isinstance(chunk, AIMessageChunk):
        text = chunk.text if hasattr(chunk, 'text') else ''
        if text:
            yield ('token', {'text': text})
