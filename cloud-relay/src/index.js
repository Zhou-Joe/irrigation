export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (request.method === 'POST' && url.pathname === '/api/upload') {
      return handleUpload(request, env);
    }

    if (request.method === 'GET' && url.pathname === '/api/pending-uploads') {
      return handlePolling(request, env);
    }

    if (request.method === 'POST' && url.pathname === '/api/mark-processed') {
      return handleMarkProcessed(request, env);
    }

    return new Response(JSON.stringify({ success: false, error: 'Not Found' }), {
      status: 404,
      headers: { 'Content-Type': 'application/json' }
    });
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

    return new Response(JSON.stringify({ success: true, data: { id } }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });
  } catch (error) {
    return new Response(JSON.stringify({ success: false, error: error.message }), {
      status: 400,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}

async function handlePolling(request, env) {
  try {
    const url = new URL(request.url);
    const lastSync = url.searchParams.get('last_sync') || '0';
    const processedParam = url.searchParams.get('processed');
    // Default to showing only unprocessed records
    const filterProcessed = processedParam !== null ? processedParam === 'true' : false;

    // List all keys and filter by timestamp
    const list = await env.WORK_LOGS.list();
    const results = [];

    for (const key of list.keys) {
      const value = await env.WORK_LOGS.get(key.name);
      if (!value) continue;

      const record = JSON.parse(value);

      // Filter by processed status (default: unprocessed only)
      if (processedParam === null && record.processed) continue;
      if (processedParam !== null && record.processed !== filterProcessed) continue;

      // Filter by timestamp
      if (record.uploaded_at > lastSync) {
        results.push({ id: key.name, ...record });
      }
    }

    return new Response(JSON.stringify({ success: true, data: { records: results } }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });
  } catch (error) {
    return new Response(JSON.stringify({ success: false, error: error.message }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}

async function handleMarkProcessed(request, env) {
  try {
    const body = await request.json();
    const ids = body.ids;

    if (!ids || !Array.isArray(ids)) {
      return new Response(JSON.stringify({
        success: false,
        error: 'Invalid request: "ids" must be an array'
      }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    if (ids.length === 0) {
      return new Response(JSON.stringify({
        success: true,
        data: { updated: 0, message: 'No IDs provided' }
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    const updatedIds = [];
    const notFoundIds = [];
    const errors = [];

    for (const id of ids) {
      try {
        const value = await env.WORK_LOGS.get(id);

        if (!value) {
          notFoundIds.push(id);
          continue;
        }

        const record = JSON.parse(value);
        record.processed = true;
        record.processed_at = new Date().toISOString();

        await env.WORK_LOGS.put(id, JSON.stringify(record));
        updatedIds.push(id);
      } catch (err) {
        errors.push({ id, error: err.message });
      }
    }

    return new Response(JSON.stringify({
      success: true,
      data: {
        updated: updatedIds.length,
        updatedIds,
        notFound: notFoundIds.length,
        notFoundIds,
        errors: errors.length > 0 ? errors : undefined
      }
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });
  } catch (error) {
    return new Response(JSON.stringify({ success: false, error: error.message }), {
      status: 400,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}
