{% load static %}
'use strict';
// Bump on release when the public shell changes. Never store business HTML,
// API responses, media, third-party resources, or mutations on a shared phone.
const CACHE = 'irrigation-shell-20261024-6';
const PREFIX = 'irrigation-shell-';
const OFFLINE = '{% url "core:pwa_offline" %}';
const SHELL = [OFFLINE, '{% static "css/pwa.css" %}?v=20261023icons2',
    '{% static "css/compact-ui.css" %}?v=20261023responsive',
    '{% static "css/responsive-ui.css" %}?v=20261023controls2',
    '{% static "css/page-ui.css" %}?v=20261024pages6',
    '{% static "js/responsive-ui.js" %}?v=20261024pages6',
    '{% static "js/pwa-offline.js" %}', '{% static "pwa/icon-192.png" %}',
    '{% static "pwa/icon-512.png" %}', '{% static "pwa/icon-maskable-512.png" %}'];

self.addEventListener('install', event => {
    event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)));
    // An update waits until the worker explicitly chooses to reopen the app.
});
self.addEventListener('activate', event => {
    event.waitUntil((async () => {
        const keys = await caches.keys();
        await Promise.all(keys.filter(key => key.startsWith(PREFIX) && key !== CACHE)
            .map(key => caches.delete(key)));
        await self.clients.claim();
    })());
});
self.addEventListener('message', event => {
    if (event.data && event.data.type === 'ACTIVATE_UPDATE') self.skipWaiting();
});
self.addEventListener('fetch', event => {
    const request = event.request;
    const url = new URL(request.url);
    if (request.method !== 'GET' || url.origin !== self.location.origin) return;
    if (request.mode === 'navigate') {
        event.respondWith(fetch(request).catch(async () => {
            const page = await caches.match(OFFLINE, {cacheName: CACHE});
            return new Response(page ? await page.text() : '<h1>当前离线，请恢复网络后重新打开工作台。</h1>', {status: 503,
                headers: {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store'}});
        }));
        return;
    }
    // Cache only public application assets. Use the full URL, including version,
    // and prefer the network so an old script cannot mask a deployed fix.
    if (!url.pathname.startsWith('{{ STATIC_URL|default:"/static/" }}') || request.headers.has('range')) return;
    event.respondWith((async () => {
        const cache = await caches.open(CACHE);
        try {
            const response = await fetch(request);
            if (response.ok && !response.redirected && response.type === 'basic') {
                try {
                    await cache.put(request, response.clone());
                    const keys = await cache.keys();
                    const extra = keys.filter(key => !SHELL.some(path => new URL(path, self.location.origin).href === key.url));
                    await Promise.all(extra.slice(0, Math.max(0, extra.length - 80)).map(key => cache.delete(key)));
                } catch (_) { /* A full device cache must not break a successful request. */ }
            }
            return response;
        } catch (error) {
            const cached = await cache.match(request);
            if (cached) return cached;
            throw error;
        }
    })());
});
