// Exercise the actual worker's fetch/lifecycle policy with browser primitives.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const origin = 'https://field.example';
const source = fs.readFileSync(path.join(__dirname, '../../core/templates/core/service-worker.js'), 'utf8')
    .replace('{% load static %}', '')
    .replace(/\{% static "([^"]+)" %\}/g, '/static/$1')
    .replace('{% url "core:pwa_offline" %}', '/offline/')
    .replace('{{ STATIC_URL|default:"/static/" }}', '/static/');

function harness() {
    const handlers = {}, stores = new Map();
    let skipCount = 0, claimed = 0;
    const key = request => new URL(typeof request === 'string' ? request : request.url, origin).href;
    function store(name) {
        if (!stores.has(name)) {
            const values = new Map();
            stores.set(name, {
                values,
                async addAll(urls) { for (const url of urls) values.set(key(url), new Response('Public offline shell')); },
                async put(request, response) { values.set(key(request), response.clone()); },
                async match(request) { return values.get(key(request))?.clone(); },
                async keys() { return [...values.keys()].map(url => ({url})); },
                async delete(request) { return values.delete(key(request)); },
            });
        }
        return stores.get(name);
    }
    const worker = {location:{origin}, clients:{async claim(){claimed++;}},
        addEventListener(name, handler) {handlers[name] = handler;}, skipWaiting(){skipCount++;}};
    const context = {self:worker, URL, Response, fetch:async () => {throw new Error('offline');},
        caches:{async open(name){return store(name);},async keys(){return [...stores.keys()];},
            async delete(name){return stores.delete(name);}, async match(request, options){return store(options.cacheName).match(request);}}};
    vm.runInNewContext(source, context);
    return {context, stores, store, get skips(){return skipCount;}, get claimed(){return claimed;},
        async lifecycle(name) {let pending; handlers[name]({waitUntil(promise){pending = promise;}}); await pending;},
        message(data) {handlers.message({data});},
        async request(url, {method='GET',mode='cors',range=false}={}) {
            let pending;
            handlers.fetch({request:{url:new URL(url, origin).href,method,mode,headers:new Headers(range?{'range':'bytes=0-10'}:{})},
                respondWith(promise){pending = promise;}});
            return pending ? await pending : null;
        }};
}
function networkResponse(body, options) {
    const response = new Response(body, options);
    Object.defineProperty(response, 'type', {value:'basic'});
    return response;
}

test('private APIs, uploads, exports, mutations and external requests bypass cache', async () => {
    const h = harness();
    for (const url of ['/api/zones-payload/', '/mobile/workorder/v2/', '/media/photo.jpg', '/work-reports/report.xlsx', 'https://tiles.example/map.png']) {
        assert.equal(await h.request(url), null);
    }
    assert.equal(await h.request('/app/', {method:'POST',mode:'navigate'}), null);
    assert.equal(await h.request('/static/file.js', {method:'POST'}), null);
    assert.equal(await h.request('/static/video.mp4', {range:true}), null);
    assert.equal(h.stores.size, 0);
});
test('successful business navigation is network only and never cached', async () => {
    const h = harness(); await h.lifecycle('install');
    h.context.fetch = async () => networkResponse('PRIVATE TASKS');
    assert.equal(await (await h.request('/work-reports/', {mode:'navigate'})).text(), 'PRIVATE TASKS');
    for (const cache of h.stores.values()) for (const value of cache.values.values()) assert.notEqual(await value.clone().text(), 'PRIVATE TASKS');
});
test('failed navigation serves generic offline help with honest failure status', async () => {
    const h = harness(); await h.lifecycle('install');
    const response = await h.request('/work-reports/?private-filter=123', {mode:'navigate'});
    assert.equal(response.status, 503);
    assert.equal(await response.text(), 'Public offline shell');
    assert.equal(response.headers.get('cache-control'), 'no-store');
});
test('storage eviction still provides a minimal offline response', async () => {
    const h = harness();
    const response = await h.request('/app/', {mode:'navigate'});
    assert.equal(response.status, 503);
    assert.match(await response.text(), /离线/);
});
test('static assets prefer network and offline lookup respects version query', async () => {
    const h = harness();
    h.context.fetch = async () => networkResponse('version one');
    assert.equal(await (await h.request('/static/js/pwa.js?v=1')).text(), 'version one');
    h.context.fetch = async () => {throw new Error('offline');};
    assert.equal(await (await h.request('/static/js/pwa.js?v=1')).text(), 'version one');
    await assert.rejects(h.request('/static/js/pwa.js?v=2'), /offline/);
    h.context.fetch = async () => networkResponse('updated network response');
    assert.equal(await (await h.request('/static/js/pwa.js?v=1')).text(), 'updated network response');
});
test('HTTP failures and login redirects cannot poison the public asset cache', async () => {
    const h = harness();
    h.context.fetch = async () => networkResponse('Missing', {status:404});
    assert.equal((await h.request('/static/missing.js')).status, 404);
    const redirected = networkResponse('LOGIN'); Object.defineProperty(redirected,'redirected',{value:true});
    h.context.fetch = async () => redirected;
    await h.request('/static/private.js');
    for (const cache of h.stores.values()) assert.equal(cache.values.size, 0);
});
test('cache quota failures do not break successful online responses', async () => {
    const h = harness(); await h.lifecycle('install');
    const cache = [...h.stores.values()][0];
    cache.put = async () => {throw new Error('QuotaExceeded');};
    h.context.fetch = async () => networkResponse('fresh online asset');
    assert.equal(await (await h.request('/static/new.js')).text(), 'fresh online asset');
});
test('updates wait for explicit activation and only remove this apps old caches', async () => {
    const h = harness(); await h.lifecycle('install');
    assert.equal(h.skips, 0);
    h.store('irrigation-shell-old'); h.store('another-app-cache');
    await h.lifecycle('activate');
    assert.equal(h.stores.has('irrigation-shell-old'), false);
    assert.equal(h.stores.has('another-app-cache'), true);
    assert.equal(h.claimed, 1);
    h.message({type:'UNKNOWN'}); assert.equal(h.skips, 0);
    h.message({type:'ACTIVATE_UPDATE'}); assert.equal(h.skips, 1);
});
test('runtime cache stays bounded while retaining required offline assets', async () => {
    const h = harness(); await h.lifecycle('install');
    const cache = [...h.stores.values()][0];
    const required = [...cache.values.keys()];
    h.context.fetch = async () => networkResponse('asset');
    for (let n=0;n<90;n++) await h.request('/static/asset-' + n + '.js');
    assert.equal(cache.values.size, required.length + 80);
    for (const url of required) assert.ok(await cache.match(url), url);
    assert.equal(await cache.match('/static/asset-0.js'), undefined);
    assert.ok(await cache.match('/static/asset-89.js'));
});
