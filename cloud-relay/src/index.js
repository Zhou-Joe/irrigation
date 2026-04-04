export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (request.method === 'POST' && url.pathname === '/api/upload') {
      return handleUpload(request, env);
    }

    if (request.method === 'GET' && url.pathname === '/api/pending-uploads') {
      return handlePolling(request, env);
    }

    return new Response('Not Found', { status: 404 });
  }
};

async function handleUpload(request, env) {
  try {
    const data = await request.json();
    const id = `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

    await env.WORK_LOGS.put(id, JSON.stringify({
      ...data,
      uploaded_at: new Date().toISOString(),
      processed: false
    }));

    return new Response(JSON.stringify({ success: true, id }), {
      headers: { 'Content-Type': 'application/json' }
    });
  } catch (error) {
    return new Response(JSON.stringify({ error: error.message }), {
      status: 400,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}

async function handlePolling(request, env) {
  try {
    const url = new URL(request.url);
    const lastSync = url.searchParams.get('last_sync') || '0';

    // List all keys and filter by timestamp
    const list = await env.WORK_LOGS.list();
    const results = [];

    for (const key of list.keys) {
      const value = await env.WORK_LOGS.get(key.name);
      const record = JSON.parse(value);

      if (!record.processed && record.uploaded_at > lastSync) {
        results.push({ id: key.name, ...record });
      }
    }

    return new Response(JSON.stringify({ records: results }), {
      headers: { 'Content-Type': 'application/json' }
    });
  } catch (error) {
    return new Response(JSON.stringify({ error: error.message }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}
