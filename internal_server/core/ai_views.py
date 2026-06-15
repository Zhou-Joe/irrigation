"""SSE endpoint for the AI data-analyst agent.

Streams agent output (LLM tokens + tool-call progress) to the browser as
Server-Sent Events. The agent runs server-side and calls ORM @tools directly.

Streaming design: the LangChain agent is async, but Django's StreamingHttpResponse
consumes a sync generator. We run the async agent on a dedicated event loop in a
worker thread, pushing each SSE event onto a thread-safe queue that the sync
generator drains — so tokens reach the browser incrementally instead of buffered.
"""
import asyncio
import json
import logging
import queue
import threading
import uuid

from django.contrib.auth.decorators import login_required
from django.http import StreamingHttpResponse, HttpResponseBadRequest, JsonResponse
from django.views.decorators.http import require_POST

from core.models import AISettings
from core.role_utils import get_user_role, ROLE_SUPER_ADMIN, ROLE_MANAGER, ROLE_FIELD_WORKER

logger = logging.getLogger(__name__)

# Roles allowed to use the AI assistant. Tighten/loosen as needed.
_ALLOWED_ROLES = {ROLE_SUPER_ADMIN, ROLE_MANAGER, ROLE_FIELD_WORKER}


def _sse(event_type: str, data: dict) -> str:
    """Format one Server-Sent Event frame."""
    return f"data: {json.dumps({'event': event_type, **data}, ensure_ascii=False)}\n\n"


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
    """Sync generator: run the async agent on a worker thread, yield SSE frames as produced."""
    q: "queue.Queue" = queue.Queue()
    _SENTINEL = object()

    def worker():
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_produce(message, thread_id, q))
        except Exception as e:  # noqa: BLE001
            logger.exception('AI agent worker failed')
            q.put(('error', {'message': f'agent error: {e}'}))
        finally:
            loop.close()
            q.put(_SENTINEL)

    # Publish the thread id to the agent's tools (run_python_code resolves a
    # per-session workspace from this). Must be set on the worker thread, so we
    # do it inside worker() — but ContextVar is per-context, and the async loop
    # runs in the same thread, so set it just before the loop starts.
    def worker_with_context():
        from core.ai_agent import set_current_thread
        set_current_thread(thread_id)
        worker()

    threading.Thread(target=worker_with_context, daemon=True).start()

    while True:
        item = q.get()
        if item is _SENTINEL:
            break
        event_type, payload = item
        yield _sse(event_type, payload)
    yield _sse('done', {})


async def _produce(message: str, thread_id: str, q):
    """Run the agent, pushing incremental SSE events onto the queue."""
    from core.ai_agent import build_agent
    from langchain_core.messages import HumanMessage

    agent = build_agent()
    config = {'configurable': {'thread_id': thread_id}}

    input_msg = {'messages': [HumanMessage(content=message)]}
    # stream_mode="messages" yields (message_chunk, metadata) pairs — each chunk
    # is an incremental AIMessageChunk (token) or a ToolMessage (tool result).
    seen_tool_calls = {}
    async for chunk, metadata in agent.astream(input_msg, config=config, stream_mode='messages'):
        chunk_type = getattr(chunk, 'type', '')
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
                    q.put(('tool_start', {'name': name, 'args': parsed_args}))
            continue
        # Tool results arrive as ToolMessage
        if chunk_type == 'tool':
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
                        q.put(('file', {
                            'name': finfo.get('name', ''),
                            'url': finfo.get('url', ''),
                            'size': finfo.get('size', 0),
                        }))
                except (json.JSONDecodeError, AttributeError, TypeError):
                    pass
            out_preview = str(content)[:800]
            q.put(('tool_end', {'name': name, 'output': out_preview}))
            continue
        # Regular AI text tokens
        if chunk_type == 'ai':
            text = chunk.text if hasattr(chunk, 'text') else ''
            if text:
                q.put(('token', {'text': text}))
