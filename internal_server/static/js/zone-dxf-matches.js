/* Batch zone-boundary review on the existing import map. */
(function () {
    'use strict';
    const bridge = window.ZoneDxfBridge;
    if (!bridge || !document.getElementById('zoneDxfMatchPanel')) return;
    const el = id => document.getElementById('zdm' + id);
    const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const idOf = row => String(row.zone_id || row.id);
    const hasDxf = row => !!(row.has_dxf || row.has_dxf_boundary || row.dxf_boundary_points?.length);
    const percent = value => Number.isFinite(Number(value)) ? (100 * Number(value)).toFixed(0) + '%' : '—';
    const chosen = row => row.candidates?.[row.choice || 0] || null;
    const groupsOf = row => chosen(row)?.group_ids || [];
    const needsReview = row => !!chosen(row) && (!(row.high_confidence && row.can_save && chosen(row).high_confidence !== false && !chosen(row).conflict) || (row.choice || 0) > 0);
    const reliable = row => !!chosen(row) && !needsReview(row);
    let rows = [], token = null, busy = false, generation = 0, limit = 60, pending = null;
    let selected = new Set(), preview = new Set(), saved = new Set(), consumed = new Map();
    const comparison = L.layerGroup();

    function message(text, error) {
        el('Status').textContent = text || '';
        el('Status').dataset.error = error ? '1' : '0';
        if (pending && !busy) {
            const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'zdm-retry';
            retry.textContent = '重试本次操作'; retry.onclick = () => execute(pending, true); el('Status').append(retry);
        }
    }
    function setBusy(value) {
        busy = value; bridge.busy(value); renderActions();
        el('List').setAttribute('aria-busy', String(value));
        el('List').querySelectorAll('input,select,button').forEach(item => { item.disabled = value || item.dataset.locked === '1'; });
    }
    function baseline() {
        return bridge.zones.map(zone => ({...zone, zone_id: zone.zone_id || zone.id,
            candidates: [], status: 'unmatched', high_confidence: false, can_save: false}));
    }
    function filtered() {
        const search = el('Search').value.trim().toLocaleLowerCase(), filter = el('Filter').value;
        return rows.filter(row => (!search || (row.code + ' ' + (row.name || '')).toLocaleLowerCase().includes(search)) &&
            (filter === 'all' || filter === 'high' && reliable(row) || filter === 'review' && chosen(row) && !reliable(row) ||
            filter === 'unmatched' && !chosen(row) || filter === 'existing' && hasDxf(row) || filter === 'saved' && saved.has(idOf(row))));
    }
    function selectedRows() { return rows.filter(row => selected.has(idOf(row))); }
    function saveProblem(items) {
        if (!token) return '请先重新计算匹配，再保存候选边界。';
        const used = new Map();
        for (const row of items) {
            if (row.sourceChanged) return '所选区域的来源已改变，请重新匹配后再保存其候选边界。';
            if (saved.has(idOf(row))) return '所选区域包含本次已保存项；如需再次更新，请重新匹配。';
            if (!chosen(row) || !groupsOf(row).length) return '所选区域中有未匹配项；请更换候选，或取消这些区域的选择后保存。';
            if (needsReview(row) && !row.reviewed) return '请先在待核对区域行内勾选“已核对候选轮廓”。';
            for (const group of groupsOf(row)) {
                if (consumed.has(group) && consumed.get(group) !== idOf(row)) return '某个候选 CAD 已分配给其它区域，请更换候选。';
                if (used.has(group) && used.get(group) !== idOf(row)) return '所选区域共用了同一个候选 CAD，请核对后保留一个，或更换候选。';
                used.set(group, idOf(row));
            }
        }
        return '';
    }
    function renderActions() {
        const items = selectedRows(), locked = busy || !!pending || bridge.state().busy;
        const problem = items.length ? saveProblem(items) : '';
        el('Run').disabled = locked || !bridge.state().ready;
        el('Run').textContent = token ? '重新匹配' : '计算匹配';
        el('Save').disabled = locked || !items.length || !!problem;
        el('SaveActive').disabled = el('Save').disabled;
        el('Activate').disabled = locked || !items.length || items.some(row => !hasDxf(row));
        el('Manual').disabled = locked || !items.length || items.some(row => !row.manual_boundary_points?.length);
        ['SelectSafe','SelectExisting','Clear','ShowAll','Search','Filter','More'].forEach(key => { el(key).disabled = busy || !!pending; });
        const updated = items.filter(hasDxf).length;
        el('SelectionHint').textContent = !items.length ? '请选择区域。保存所选 DXF 不切换当前来源；也可保存并立即启用。' :
            (problem ? problem + ' ' : '') + '保存所选 DXF 不切换当前来源。' + (updated ? updated + ' 个区域已有 DXF，本次保存将更新其 DXF 边界。' : '') +
            (items.some(row => !hasDxf(row)) ? '启用已有 DXF 仅适用于全部已保存 DXF 的选择。' : '可独立切换这些区域的边界来源。') +
            (items.some(row => !row.manual_boundary_points?.length) ? '部分区域无手绘边界，不能批量恢复手绘。' : '');
        el('Save').title = '保存 DXF，不切换当前边界来源';
        el('Count').textContent = '筛选 ' + filtered().length + ' / ' + rows.length + ' 个区域 · 已选 ' + items.length + ' · 本次已保存 ' + saved.size;
    }
    function rowMarkup(row) {
        const id = idOf(row), candidate = chosen(row), done = saved.has(id);
        const label = done ? '本次已保存' : candidate ? reliable(row) ? '可靠匹配' : '待核对' : token ? '未匹配' : '待匹配';
        const options = (row.candidates || []).map((item, index) => '<option value="' + index + '"' + ((row.choice || 0) === index ? ' selected' : '') + '>' +
            esc(item.label || item.group_ids?.join(' + ') || '候选 ' + (index + 1)) + ' · 重叠 ' + percent(item.iou) + '</option>').join('');
        const locked = busy || !!pending;
        return '<article class="zdm-row' + (preview.has(id) ? ' is-focused' : '') + (selected.has(id) ? ' is-selected' : '') + '" data-zone="' + esc(id) + '">' +
            '<div class="zdm-row-head"><input type="checkbox" data-select' + (selected.has(id) ? ' checked' : '') + (locked ? ' disabled' : '') + ' aria-label="选择区域 ' + esc(row.code) + '">' +
            '<button type="button" class="zdm-focus" data-focus' + (locked ? ' disabled' : '') + '><b>' + esc(row.code) + '</b><span>' + esc(row.name || '') + '</span></button><span class="zdm-tag ' + (done || reliable(row) ? 'is-good' : candidate ? 'is-review' : '') + '">' + label + '</span></div>' +
            '<p class="zdm-source">当前来源：<b>' + (row.boundary_source === 'dxf' ? 'DXF' : '手绘') + '</b>' + (hasDxf(row) ? ' · 已有 DXF' : ' · 尚无 DXF') + '</p>' +
            (candidate ? '<label class="zdm-candidate-label">候选 CAD<select data-candidate' + (locked || done ? ' disabled' : '') + (done ? ' data-locked="1"' : '') + '>' + options + '</select></label>' +
                '<p class="zdm-metrics">重叠率 ' + percent(candidate.iou) + ' · 手绘覆盖 ' + percent(candidate.manual_coverage) + ' · CAD 覆盖 ' + percent(candidate.cad_coverage) + '</p>' +
                '<details class="zdm-detail"><summary>匹配说明</summary><p>' + esc(candidate.reason || row.reason || '') + '</p><p>面积比 ' + esc(Number(candidate.area_ratio || 0).toFixed(2)) + ' · 中心偏移 ' + esc(Number(candidate.centroid_distance_m || 0).toFixed(1)) + ' m</p></details>' +
                (candidate.conflict ? '<p class="zdm-warning">此候选也与其它区域接近，请核对归属，不能重复分配。</p>' : '') +
                (needsReview(row) && !done ? '<label class="zdm-review"><input type="checkbox" data-reviewed' + (row.reviewed ? ' checked' : '') + (locked ? ' disabled' : '') + '>已核对候选轮廓</label>' : '') :
                '<p class="zdm-hint">' + esc(row.reason || (hasDxf(row) ? '可查看已有边界或批量切换来源。' : '上传并配准图纸后计算匹配。')) + '</p>') +
            (hasDxf(row) && candidate && !done ? '<p class="zdm-overwrite">已有 DXF 将在保存时更新；手绘边界保留。</p>' : '') + '</article>';
    }
    function render() {
        const matches = filtered();
        el('List').innerHTML = matches.slice(0, limit).map(rowMarkup).join('') || '<p class="zdm-empty">没有符合筛选条件的区域。</p>';
        el('More').hidden = matches.length <= limit;
        renderActions();
    }
    function coordinates(value) {
        if (!Array.isArray(value) || !value.length) return null;
        if (typeof value[0] === 'number') return value;
        if (value[0]?.lat !== undefined || value[0]?.latitude !== undefined) {
            return value.map(point => [Number(point.lat ?? point.latitude), Number(point.lng ?? point.longitude)]);
        }
        return value.map(coordinates).filter(Boolean);
    }
    function showAll() {
        preview.clear(); comparison.clearLayers();
        if (bridge.map.hasLayer(comparison)) bridge.map.removeLayer(comparison);
        bridge.comparison(false); el('Legend').hidden = true;
        el('List').querySelectorAll('.is-focused').forEach(row => row.classList.remove('is-focused'));
    }
    function compare(ids, fit) {
        preview = new Set(ids);
        if (!preview.size) { showAll(); return; }
        bridge.lock(); bridge.comparison(true);
        comparison.clearLayers(); comparison.addTo(bridge.map);
        const bounds = L.latLngBounds([]);
        for (const row of rows.filter(item => preview.has(idOf(item)))) {
            const versions = [
                [coordinates(row.dxf_boundary_points), {color:'#e5b560',weight:2.5,dashArray:'3 4',fillOpacity:.015}],
                [coordinates(row.manual_boundary_points), {color:'#f4f5ed',weight:3,dashArray:'7 5',fillOpacity:.025}],
                [bridge.groupBoundary(groupsOf(row)), {color:'#5fd59a',weight:3,fillOpacity:.1}],
            ];
            let labelLayer = null;
            for (const [boundary, style] of versions) {
                if (!boundary?.length) continue;
                const layer = L.polygon(boundary, {...style,interactive:false}).addTo(comparison);
                bounds.extend(layer.getBounds()); labelLayer = layer;
            }
            if (labelLayer) labelLayer.bindTooltip(esc(row.code), {permanent:true,direction:'center',className:'zdm-map-label'});
        }
        el('Legend').hidden = false;
        if (fit && bounds.isValid()) bridge.map.fitBounds(bounds, {padding:[34,34],maxZoom:20});
    }
    async function post(payload) {
        const body = new FormData(); Object.entries(payload).forEach(([key,value]) => body.append(key,value));
        let response;
        try { response = await fetch('', {method:'POST',credentials:'same-origin',headers:{'X-CSRFToken':bridge.csrf()},body}); }
        catch (_) { const error = new Error('网络连接中断，请重试本次操作。'); error.uncertain = true; throw error; }
        let data;
        try { data = await response.json(); }
        catch (_) { const error = new Error('未能确认操作结果，请重试本次操作。'); error.uncertain = true; throw error; }
        if (!response.ok || !data.success) {
            const error = new Error(data.message || data.error || '操作未完成，请重试。'); error.uncertain = !!data.uncertain || response.status >= 500; throw error;
        }
        return data;
    }
    async function run() {
        if (busy || pending || !bridge.state().ready) return;
        const version = bridge.state().version, mine = ++generation;
        bridge.lock(); showAll(); setBusy(true); message('正在比较手绘边界与 CAD 轮廓…');
        try {
            const data = await post({action:'auto_match',transformed_json:JSON.stringify(bridge.state().transformed)});
            if (mine !== generation || version !== bridge.state().version) return;
            token = data.match_token; selected.clear(); consumed.clear(); saved.clear();
            rows = (data.zones || []).map(row => ({...row, candidates:row.candidates || [], choice:0, reviewed:false}));
            bridge.update(rows);
            const count = rows.filter(row => row.high_confidence && !hasDxf(row)).length;
            message('匹配已完成：' + count + ' 个可靠新匹配。请点击区域对照后选择保存；已有 DXF 不会自动覆盖。');
        } catch (error) {
            if (mine === generation) { token = null; message(error.message, true); }
        } finally { setBusy(false); render(); }
    }
    function updateRows(updated) {
        bridge.update(updated);
        for (const item of updated || []) {
            const row = rows.find(value => idOf(value) === idOf(item));
            if (row) Object.assign(row, item);
        }
    }
    async function execute(attempt, retry) {
        if (busy) return;
        pending = attempt; setBusy(true); message('正在保存所选区域…');
        try {
            let data;
            if (retry) {
                try {
                    const response = await fetch('/api/submissions/' + attempt.payload.submission_key + '/', {credentials:'same-origin',cache:'no-store'});
                    const receipt = await response.json();
                    if (receipt.found && receipt.result?.success) data = receipt.result;
                } catch (_) { /* The original idempotent request remains safe to retry. */ }
            }
            if (!data) data = await post(attempt.payload);
            pending = null; updateRows(data.zones || []);
            if (attempt.kind === 'save') {
                for (const row of attempt.items) { saved.add(row.id); row.groups.forEach(group => consumed.set(group,row.id)); }
                bridge.update([], attempt.items.flatMap(row => row.groups));
            } else {
                attempt.items.forEach(item => { const row = rows.find(value => idOf(value) === item.id); if (row) row.sourceChanged = true; });
            }
            attempt.items.forEach(row => selected.delete(row.id));
            message(data.message || (attempt.kind === 'save' ? '所选 DXF 边界已保存。' : '所选区域的边界来源已更新。'));
            compare(attempt.items.map(row => row.id), false);
        } catch (error) {
            if (!error.uncertain) pending = null;
            message(error.message, true);
        } finally {
            setBusy(false); render();
            if (pending) message(el('Status').textContent, true);
        }
    }
    function save(mode) {
        const items = selectedRows();
        if (busy || pending || !items.length || saveProblem(items)) return;
        const assignments = items.map(row => ({zone_id:row.zone_id || row.id, group_ids:groupsOf(row), expected_revision:row.expected_revision,
            reviewed:!!row.reviewed || !needsReview(row), overwrite_existing:hasDxf(row)}));
        execute({kind:'save',items:items.map(row => ({id:idOf(row),groups:[...groupsOf(row)]})),payload:{action:'batch_assign',match_token:token,
            submission_key:crypto.randomUUID(),mode,assignments:JSON.stringify(assignments)}});
    }
    function switchSource(source) {
        const items = selectedRows();
        if (busy || pending || !items.length || items.some(row => source === 'dxf' ? !hasDxf(row) : !row.manual_boundary_points?.length)) return;
        execute({kind:'source',items:items.map(row => ({id:idOf(row),groups:[]})),payload:{action:'batch_switch_source',source,
            submission_key:crypto.randomUUID(),zones:JSON.stringify(items.map(row => ({zone_id:row.zone_id || row.id,expected_revision:row.expected_revision})))}});
    }
    function invalidate(reason) {
        generation++; token = null; selected.clear(); showAll(); rows = baseline();
        message(reason || '位置或配准已改变，请重新计算匹配。'); render();
    }
    el('List').addEventListener('click', event => {
        if (busy || pending) return;
        const button = event.target.closest('[data-focus]');
        if (!button) return;
        compare([button.closest('[data-zone]').dataset.zone], true); render();
    });
    el('List').addEventListener('change', event => {
        if (busy || pending) return;
        const card = event.target.closest('[data-zone]'), row = rows.find(item => idOf(item) === card?.dataset.zone);
        if (!row) return;
        if (event.target.matches('[data-select]')) {
            event.target.checked ? selected.add(idOf(row)) : selected.delete(idOf(row));
            compare([...selected], true); render();
        } else if (event.target.matches('[data-candidate]')) {
            row.choice = Number(event.target.value); row.reviewed = false;
            compare(selected.has(idOf(row)) ? [...selected] : [idOf(row)], true); render();
        } else if (event.target.matches('[data-reviewed]')) { row.reviewed = event.target.checked; renderActions(); }
    });
    ['Search','Filter'].forEach(key => el(key).addEventListener(key === 'Search' ? 'input' : 'change', () => { limit = 60; render(); }));
    el('Run').onclick = run; el('ShowAll').onclick = showAll;
    el('More').onclick = () => { limit += 60; render(); };
    el('Clear').onclick = () => { selected.clear(); showAll(); render(); };
    el('SelectSafe').onclick = () => {
        filtered().filter(row => !hasDxf(row) && !saved.has(idOf(row)) && !row.sourceChanged && row.high_confidence && row.can_save &&
            chosen(row) && groupsOf(row).length && !needsReview(row) && groupsOf(row).every(group => !consumed.has(group)))
            .forEach(row => selected.add(idOf(row)));
        compare([...selected], true); render();
    };
    el('SelectExisting').onclick = () => { filtered().filter(hasDxf).forEach(row => selected.add(idOf(row))); compare([...selected],true); render(); };
    el('Save').onclick = () => save('save_only'); el('SaveActive').onclick = () => save('save_and_activate');
    el('Activate').onclick = () => switchSource('dxf'); el('Manual').onclick = () => switchSource('manual');
    window.ZoneDxfMatches = {invalidate, showAll, geometryReady(auto) { renderActions(); if (auto && bridge.state().ready) run(); },
        legacyUpdated(data) { updateRows(data.zones || []); invalidate('区域边界已更新。已有 DXF 进度已保留，如需继续自动分配请重新匹配。'); }};
    rows = baseline(); render();
})();
