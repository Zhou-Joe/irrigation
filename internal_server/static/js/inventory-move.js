/* Inline inventory-directory assignment, shared by EnGenie result cards. */
(function (root) {
    'use strict';
    const mounted = new Set();
    const catalogCache = new Map();
    let nextId = 0;
    const rootLabel = '库存目录（根层）';
    const parentOf = node => node && node.parent !== '#' && node.parent != null ? String(node.parent) : '';
    const nameOf = node => String(node?.data?.name_zh || node?.data?.code || node?.text || '未命名');

    async function jsonRequest(url, options) {
        const response = await fetch(url, {credentials: 'same-origin', ...options});
        let data;
        try { data = await response.json(); }
        catch (_) { throw new Error(response.status === 403 ? '无权限，请重新登录后再试。' : '未能读取目录，请稍后重试。'); }
        if (!response.ok || data.success === false) throw new Error(data.message || '操作失败，请稍后重试。');
        return data;
    }
    function csrf() {
        const cookie = document.cookie.split(';').map(item => item.trim()).find(item => item.startsWith('csrftoken='));
        return cookie ? decodeURIComponent(cookie.slice(10)) : document.querySelector('[name="csrfmiddlewaretoken"]')?.value || '';
    }
    function loadCatalog(url, partId) {
        let entry = catalogCache.get(url);
        // A quote may have created a part since the previous resolved fetch.
        // Invalidate that snapshot once; concurrent mounts share the next fetch.
        if (entry?.data && !entry.data.some(node => String(node.id) === partId)) {
            catalogCache.delete(url); entry = null;
        }
        if (!entry) {
            entry = {data: null};
            entry.promise = jsonRequest(url, {cache: 'no-store'}).then(data => {
                entry.data = Array.isArray(data) ? data : null; return data;
            }).catch(error => { if (catalogCache.get(url) === entry) catalogCache.delete(url); throw error; });
            catalogCache.set(url, entry);
        }
        return entry.promise;
    }

    function mount(host, options) {
        options = options || {};
        if (!host || !options.partId) throw new Error('目录关联需要容器和部件编号');
        const id = String(options.partId), uid = 'iv-move-' + (++nextId), controller = new AbortController();
        let nodes = [], byId = new Map(), source = null, destination = null, choices = [], active = -1;
        let stopped = false, loading = false, saving = false, expanded = false, generation = 0;
        const listeners = [];
        const shell = document.createElement('section');
        shell.className = 'iv-move';
        shell.setAttribute('aria-label', '关联库存目录');
        shell.innerHTML = '<div class="iv-move-heading"><svg class="ui-icon" aria-hidden="true"><use href="#pwa-folder"/></svg><strong>关联库存目录</strong></div>' +
            '<p class="iv-move-current"><span>当前位置</span><b data-move-current></b></p>' +
            '<label class="iv-move-label" for="' + uid + '">目标目录</label>' +
            '<div class="iv-move-controls"><div class="iv-move-picker"><input id="' + uid + '" type="search" autocomplete="off" placeholder="搜索目录名称或编号…" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="' + uid + '-list"><div class="iv-move-options" id="' + uid + '-list" role="listbox" aria-label="可选目录" hidden></div></div><button type="button" class="iv-move-save" disabled>保存目录</button></div>' +
            '<p class="iv-move-target" data-move-target></p><p class="iv-move-status" role="status" aria-live="polite"></p>';
        host.append(shell);
        const input = shell.querySelector('input'), list = shell.querySelector('[role="listbox"]');
        const save = shell.querySelector('.iv-move-save'), current = shell.querySelector('[data-move-current]');
        const target = shell.querySelector('[data-move-target]'), status = shell.querySelector('.iv-move-status');
        function on(element, event, callback) { element.addEventListener(event, callback); listeners.push(() => element.removeEventListener(event, callback)); }
        function message(text, error) { status.textContent = text; status.dataset.error = error ? '1' : '0'; }
        function path(node) {
            const names = [], seen = new Set();
            while (node && !seen.has(String(node.id))) {
                seen.add(String(node.id)); names.unshift(nameOf(node)); node = byId.get(parentOf(node));
            }
            return ['库存目录', ...names].join(' / ');
        }
        function isDescendant(node) {
            const seen = new Set();
            while (node && !seen.has(String(node.id))) {
                const key = String(node.id);
                if (key === id) return true;
                seen.add(key); node = byId.get(parentOf(node));
            }
            return false;
        }
        function sync() {
            current.textContent = source ? path(source) : '正在读取…';
            target.textContent = destination === null ? '请选择一个目录，也可保留在根层。' : '目标：' + (destination ? path(byId.get(destination)) : rootLabel);
            save.disabled = loading || saving || !source || destination === null || destination === parentOf(source);
            save.textContent = saving ? '正在保存…' : '保存目录';
            input.disabled = loading || saving || !source;
            shell.setAttribute('aria-busy', loading || saving ? 'true' : 'false');
        }
        function close() {
            expanded = false; list.hidden = true; input.setAttribute('aria-expanded', 'false'); input.removeAttribute('aria-activedescendant');
        }
        function highlight(index) {
            active = index;
            [...list.querySelectorAll('[role="option"]')].forEach((item, i) => {
                item.classList.toggle('is-active', i === active);
                if (i === active) { input.setAttribute('aria-activedescendant', item.id); item.scrollIntoView({block: 'nearest'}); }
            });
        }
        function choose(index) {
            const choice = choices[index];
            if (!choice) return;
            destination = choice.id; input.value = choice.label; close(); message('', false); sync();
        }
        function renderChoices() {
            if (!source || loading || saving) return;
            const query = input.value.trim().toLocaleLowerCase();
            const directories = nodes.filter(node => node.data?.node_type === 'category' && !isDescendant(node))
                .map(node => ({id: String(node.id), label: path(node), code: node.data?.code || ''}))
                .filter(choice => !query || (choice.label + ' ' + choice.code).toLocaleLowerCase().includes(query));
            choices = [{id: '', label: rootLabel}, ...directories.slice(0, 60)];
            list.replaceChildren(); active = -1;
            choices.forEach((choice, index) => {
                const item = document.createElement('button'); item.type = 'button'; item.tabIndex = -1;
                item.id = uid + '-option-' + index; item.setAttribute('role', 'option');
                item.setAttribute('aria-selected', String(destination === choice.id));
                item.className = 'iv-move-option'; item.textContent = choice.label; item.title = choice.label;
                item.onpointerdown = event => event.preventDefault(); item.onclick = () => choose(index);
                list.append(item);
            });
            if (!directories.length || directories.length > 60) {
                const hint = document.createElement('p'); hint.className = 'iv-move-hint';
                hint.textContent = directories.length > 60 ? '已显示前 60 个目录，请继续输入以缩小范围。' : '没有匹配目录，可选择根层或更换搜索内容。'; list.append(hint);
            }
            expanded = true; list.hidden = false; input.setAttribute('aria-expanded', 'true'); input.removeAttribute('aria-activedescendant');
        }
        async function refreshCatalog(catalog) {
            if (stopped || saving) return;
            const version = ++generation;
            const previousParent = parentOf(source), previousDestination = destination, previousQuery = input.value, hadSource = !!source;
            loading = true; close(); sync(); message('正在读取库存目录…', false);
            try {
                let data = catalog;
                if (typeof data === 'function') data = await data();
                else if (data && typeof data.then === 'function') data = await data;
                // Extraction catalogs are summaries rather than jsTree nodes;
                // fetch the real hierarchy instead of treating them as nodes.
                if (!Array.isArray(data) || !data.some(node => String(node.id) === id) || data.some(node => !node.data || !('parent' in node))) {
                    data = await loadCatalog(options.treeUrl || '/inventory/tree.json', id);
                }
                if (stopped || version !== generation) return;
                if (!Array.isArray(data)) throw new Error('库存目录格式无效，请重试。');
                nodes = data.map(node => ({...node, data: {...node.data}}));
                byId = new Map(nodes.map(node => [String(node.id), node])); source = byId.get(id);
                if (!source) throw new Error('此部件已停用或不存在，请刷新报价结果。');
                const chosen = byId.get(previousDestination);
                if (hadSource && previousDestination !== previousParent &&
                    (previousDestination === null || previousDestination === '' || chosen?.data?.node_type === 'category' && !isDescendant(chosen))) {
                    destination = previousDestination; input.value = previousQuery;
                } else { destination = parentOf(source); input.value = destination ? path(byId.get(destination)) : rootLabel; }
                message('', false);
            } catch (error) {
                if (stopped || version !== generation) return;
                source = null; message(error.message || '目录读取失败，请重试。', true);
            } finally {
                if (!stopped && version === generation) { loading = false; sync(); }
            }
        }
        async function submit() {
            if (save.disabled) return;
            saving = true; close(); sync(); message('正在保存目录…', false);
            try {
                const body = new FormData(); body.append('parent_id', destination);
                const data = await jsonRequest((options.moveUrl || '/inventory/node/{id}/move/').replace('{id}', encodeURIComponent(id)), {
                    method: 'POST', signal: controller.signal, body,
                    headers: {'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest'}
                });
                if (stopped) return;
                source.parent = data.parent_id == null ? '#' : String(data.parent_id);
                message(data.message || '目录已保存', false);
                catalogCache.clear();
                for (const control of mounted) if (control !== api) control.refreshCatalog();
                const detail = {...data, reason: 'move', partId: id};
                document.dispatchEvent(new CustomEvent('inventory:catalog-changed', {detail}));
                if (typeof options.onMoved === 'function') {
                    try { options.onMoved(data); } catch (_) { /* The move is already saved. */ }
                }
            } catch (error) {
                if (!stopped) message(error.message || '保存失败，请重试。', true);
            } finally { if (!stopped) { saving = false; sync(); } }
        }
        on(input, 'focus', () => { if (destination !== null) input.select(); renderChoices(); });
        on(input, 'input', () => { destination = null; sync(); renderChoices(); });
        on(input, 'blur', close);
        on(input, 'keydown', event => {
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                event.preventDefault(); if (!expanded) renderChoices();
                highlight(Math.max(0, Math.min(choices.length - 1, active + (event.key === 'ArrowDown' ? 1 : -1))));
            } else if (event.key === 'Enter') { event.preventDefault(); if (expanded && active >= 0) choose(active); }
            else if (event.key === 'Escape') { event.stopPropagation(); close(); }
        });
        on(save, 'click', submit);
        const api = {refreshCatalog, destroy() {
            if (stopped) return; stopped = true; generation++; controller.abort(); listeners.forEach(remove => remove()); shell.remove(); mounted.delete(api);
        }};
        mounted.add(api); refreshCatalog(options.catalog);
        return api;
    }
    root.FOSInventoryMove = {mount, refreshCatalog: catalog => {
        catalogCache.clear();
        return Promise.all([...mounted].map(control => control.refreshCatalog(catalog)));
    }};
})(window);
