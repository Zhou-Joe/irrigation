/* Batch comparison and per-zone position drafts on the existing import map. */
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
    let focused = null, moving = false, handle = null, gesture = null, paintFrame = null;
    const comparison = L.layerGroup(), layersByZone = new Map(), centers = new Map(), offsets = new Map(), undo = new Map();
    const offsetOf = id => offsets.get(String(id)) || {lat:0,lng:0};
    const shifted = row => offsets.has(idOf(row));
    const usingSaved = row => hasDxf(row) && (row.editSource === 'existing' || saved.has(idOf(row)) || row.sourceChanged || !chosen(row));
    const operation = row => usingSaved(row) ? 'translate' : chosen(row) && groupsOf(row).length ? 'save' : null;
    const baseBoundary = row => usingSaved(row) ? coordinates(row.dxf_boundary_points) : bridge.groupBoundary(groupsOf(row));

    function message(text, error) {
        el('Status').textContent = text || ''; el('Status').dataset.error = error ? '1' : '0';
        if (pending && !busy) {
            const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'zdm-retry';
            retry.textContent = '重试本次操作'; retry.onclick = () => execute(pending,true); el('Status').append(retry);
        }
    }
    function setBusy(value) {
        if (value) setMoving(false);
        busy = value; bridge.busy(value); renderActions(); el('List').setAttribute('aria-busy',String(value));
        el('List').querySelectorAll('input,select,button').forEach(item => { item.disabled = value || item.dataset.locked === '1'; });
    }
    function baseline() { return bridge.zones.map(zone => ({...zone,zone_id:zone.zone_id || zone.id,candidates:[],status:'unmatched',high_confidence:false,can_save:false})); }
    function filtered() {
        const search = el('Search').value.trim().toLocaleLowerCase(), filter = el('Filter').value;
        return rows.filter(row => (!search || (row.code + ' ' + (row.name || '')).toLocaleLowerCase().includes(search)) &&
            (filter === 'all' || filter === 'high' && reliable(row) || filter === 'review' && chosen(row) && !reliable(row) ||
            filter === 'unmatched' && !chosen(row) || filter === 'existing' && hasDxf(row) || filter === 'saved' && saved.has(idOf(row))));
    }
    function selectedRows() { return rows.filter(row => selected.has(idOf(row))); }
    function saveProblem(items) {
        const types = new Set(items.map(operation));
        if (types.has(null)) return '所选区域中有未匹配且没有已保存 DXF 的项目，请先选择候选。';
        if (types.size > 1) return '候选 CAD 保存与已有 DXF 位置微调请分开选择、分别保存。';
        if (types.has('translate')) return items.some(shifted) ? '' : '所选已有 DXF 尚无未保存的位置微调；可直接使用下方来源切换。';
        if (!token) return '请先重新计算匹配，再保存候选边界。';
        const used = new Map();
        for (const row of items) {
            if (row.sourceChanged) return '所选区域来源已改变，请重新匹配后保存候选。';
            if (needsReview(row) && !row.reviewed) return '请先在待核对区域行内勾选“已核对候选轮廓”。';
            for (const group of groupsOf(row)) {
                if (consumed.has(group) && consumed.get(group) !== idOf(row)) return '某个候选 CAD 已分配给其它区域，请更换候选。';
                if (used.has(group) && used.get(group) !== idOf(row)) return '所选区域共用了同一个候选 CAD，请核对后保留一个。';
                used.set(group,idOf(row));
            }
        }
        return '';
    }
    function renderActions() {
        const items = selectedRows(), locked = busy || !!pending || !!gesture || bridge.state().busy;
        const problem = items.length ? saveProblem(items) : '', translate = items.length && items.every(row => operation(row) === 'translate');
        el('Run').disabled = locked || !bridge.state().ready; el('Run').textContent = token ? '重新匹配' : '计算匹配';
        el('Save').disabled = locked || !items.length || !!problem; el('SaveActive').disabled = el('Save').disabled;
        el('Save').textContent = translate ? '保存所选位置' : '保存所选 DXF';
        el('SaveActive').textContent = translate ? '保存位置并启用 DXF' : '保存并启用 DXF';
        el('Activate').disabled = locked || !items.length || items.some(row => !hasDxf(row) || shifted(row));
        el('Manual').disabled = locked || !items.length || items.some(row => !row.manual_boundary_points?.length || shifted(row));
        ['SelectSafe','SelectExisting','Clear','ShowAll','Search','Filter','More'].forEach(key => { el(key).disabled = busy || !!pending || !!gesture; });
        const changed = items.filter(shifted).length;
        el('SelectionHint').textContent = !items.length ? '请选择区域。微调仅在当前地图预览，点击保存后才写入。' :
            (problem ? problem + ' ' : '') + (changed ? changed + ' 个区域含未保存微调，保存时手绘与 DXF 同步移动。' : '保存 DXF 不切换当前来源，也可保存并启用。') +
            (items.some(row => !hasDxf(row)) ? '已有 DXF 的区域才可独立切换来源。' : '') +
            (changed ? '请先保存或取消微调，再使用仅切换来源的按钮。' : '');
        el('Save').title = translate ? '只保存这些区域的位置微调，不切换来源' : '保存 DXF 及所选区域的微调，不切换来源';
        el('Count').textContent = '筛选 ' + filtered().length + ' / ' + rows.length + ' 个区域 · 已选 ' + items.length + ' · 未保存微调 ' + offsets.size + ' · 本次已保存 ' + saved.size;
        renderMoveActions();
    }
    function rowMarkup(row) {
        const id = idOf(row), candidate = chosen(row), done = saved.has(id), existing = usingSaved(row);
        const label = shifted(row) ? '微调未保存' : done ? '本次已保存' : candidate ? reliable(row) ? '可靠匹配' : '待核对' : hasDxf(row) ? '已有 DXF' : token ? '未匹配' : '待匹配';
        const options = (row.candidates || []).map((item,index) => '<option value="' + index + '"' + ((row.choice || 0) === index ? ' selected' : '') + '>' +
            esc(item.label || item.group_ids?.join(' + ') || '候选 ' + (index+1)) + ' · 重叠 ' + percent(item.iou) + '</option>').join('');
        const locked = busy || !!pending;
        return '<article class="zdm-row' + (preview.has(id) ? ' is-focused' : '') + (focused === id ? ' is-active' : '') + (selected.has(id) ? ' is-selected' : '') + '" data-zone="' + esc(id) + '">' +
            '<div class="zdm-row-head"><input type="checkbox" data-select' + (selected.has(id) ? ' checked' : '') + (locked ? ' disabled' : '') + ' aria-label="选择区域 ' + esc(row.code) + '">' +
            '<button type="button" class="zdm-focus" data-focus' + (locked ? ' disabled' : '') + '><b>' + esc(row.code) + '</b><span>' + esc(row.name || '') + '</span></button><span class="zdm-tag ' + (shifted(row) ? 'is-review' : done || reliable(row) ? 'is-good' : candidate ? 'is-review' : '') + '">' + label + '</span></div>' +
            '<p class="zdm-source">当前来源：<b>' + (row.boundary_source === 'dxf' ? 'DXF' : '手绘') + '</b>' + (hasDxf(row) ? ' · 已有 DXF' : ' · 尚无 DXF') + '</p>' +
            (candidate && hasDxf(row) && !done && !row.sourceChanged ? '<label class="zdm-candidate-label">微调 / 保存基准<select data-edit-source' + (locked ? ' disabled' : '') + '><option value="candidate"' + (!existing ? ' selected' : '') + '>本次候选 CAD</option><option value="existing"' + (existing ? ' selected' : '') + '>已保存 DXF</option></select></label>' : '') +
            (candidate && !existing ? '<label class="zdm-candidate-label">候选 CAD<select data-candidate' + (locked ? ' disabled' : '') + '>' + options + '</select></label>' +
                '<p class="zdm-metrics">重叠率 ' + percent(candidate.iou) + ' · 手绘覆盖 ' + percent(candidate.manual_coverage) + ' · CAD 覆盖 ' + percent(candidate.cad_coverage) + '</p>' +
                '<details class="zdm-detail"><summary>匹配说明</summary><p>' + esc(candidate.reason || row.reason || '') + '</p><p>面积比 ' + esc(Number(candidate.area_ratio || 0).toFixed(2)) + ' · 中心偏移 ' + esc(Number(candidate.centroid_distance_m || 0).toFixed(1)) + ' m</p></details>' +
                (candidate.conflict ? '<p class="zdm-warning">此候选也与其它区域接近，请核对归属，不能重复分配。</p>' : '') +
                (needsReview(row) ? '<label class="zdm-review"><input type="checkbox" data-reviewed' + (row.reviewed ? ' checked' : '') + (locked ? ' disabled' : '') + '>已核对候选轮廓</label>' : '') :
                '<p class="zdm-hint">' + esc(existing ? '可微调已保存 DXF：手绘与 DXF 同步移动，点击保存后生效。' : row.reason || '上传并配准图纸后计算匹配。') + '</p>') +
            (shifted(row) ? '<p class="zdm-offset">本次位置微调约 ' + movement(row,offsetOf(id)).toFixed(1) + ' m，尚未保存。</p>' : '') +
            (hasDxf(row) && candidate && !existing ? '<p class="zdm-overwrite">保存将更新已有 DXF；有微调时手绘边界也按相同距离移动。</p>' : '') + '</article>';
    }
    function render() {
        const matches = filtered(); el('List').innerHTML = matches.slice(0,limit).map(rowMarkup).join('') || '<p class="zdm-empty">没有符合筛选条件的区域。</p>';
        el('More').hidden = matches.length <= limit; renderActions();
    }
    function coordinates(value) {
        if (!Array.isArray(value) || !value.length) return null;
        if (value.length >= 2 && typeof value[0] === 'number' && typeof value[1] === 'number') return Number.isFinite(value[0]) && Number.isFinite(value[1]) ? [value[0],value[1]] : null;
        if (value[0]?.lat !== undefined || value[0]?.latitude !== undefined) {
            const ring = value.map(point => [Number(point.lat ?? point.latitude),Number(point.lng ?? point.longitude)]);
            return ring.every(point => point.every(Number.isFinite)) ? ring : null;
        }
        const children = value.map(coordinates); return children.every(Boolean) ? children : null;
    }
    function translated(value, delta) { return typeof value[0] === 'number' ? [value[0]+delta.lat,value[1]+delta.lng] : value.map(child => translated(child,delta)); }
    function setOffset(id, delta) {
        if (Math.abs(delta.lat)<1e-12 && Math.abs(delta.lng)<1e-12) offsets.delete(String(id));
        else offsets.set(String(id),{lat:delta.lat,lng:delta.lng});
    }
    function centerOf(row) {
        if (centers.has(idOf(row))) return centers.get(idOf(row));
        const geometry = baseBoundary(row) || coordinates(row.manual_boundary_points);
        return geometry?.length ? L.polygon(geometry).getBounds().getCenter() : null;
    }
    function movement(row, delta) {
        const center = centerOf(row); return Math.hypot(delta.lat*111320,delta.lng*111320*Math.cos((center?.lat || 0)*Math.PI/180));
    }
    function movable(row) { return !!row && !!baseBoundary(row)?.length; }
    function applyOffset(id) {
        for (const item of layersByZone.get(String(id)) || []) {
            item.layer.setLatLngs(translated(item.boundary,offsetOf(id)));
            item.layer.getTooltip?.()?.setLatLng(item.layer.getBounds().getCenter());
        }
    }
    function paintOffset(id) {
        if (paintFrame === null) paintFrame=requestAnimationFrame(() => { paintFrame=null;applyOffset(id); });
    }
    function restoreMapDrag(current) { if (current?.mapDragging) bridge.map.dragging.enable(); }
    function removeHandle() {
        if (paintFrame !== null) { cancelAnimationFrame(paintFrame);paintFrame=null; }
        const current = gesture; gesture = null;
        if (current) { setOffset(current.id,current.before); applyOffset(current.id); restoreMapDrag(current); }
        if (handle) { handle.off(); handle.dragging?.disable(); comparison.removeLayer(handle); handle=null; }
        bridge.map.getContainer().classList.remove('zdm-positioning','zdm-dragging'); bridge.scopedDragging?.(false);
    }
    function renderMoveActions() {
        const row = rows.find(item => idOf(item)===focused), locked = busy || !!pending || !!gesture || bridge.state().busy;
        if (el('Move')) { el('Move').disabled=locked || !preview.has(focused) || !movable(row); el('Move').setAttribute('aria-pressed',String(moving)); el('Move').textContent=moving ? '结束微调' : '微调区域'; }
        if (el('Undo')) el('Undo').disabled=locked || !(undo.get(focused)?.length);
        if (el('Reset')) el('Reset').disabled=locked || !offsets.has(focused);
        if (el('MoveHint')) el('MoveHint').textContent=!row || !preview.has(focused) ? '点击区域行或对照轮廓后，可微调该区域；其它区域保持不动。' :
            '当前区域 ' + row.code + (shifted(row) ? ' · 本次偏移约 ' + movement(row,offsetOf(focused)).toFixed(1) + ' m。' : '。') +
            (moving ? '拖动地图上的移动手柄，手绘与 DXF 将同步移动。' : '点击“微调区域”显示移动手柄。') + '点击保存前不会写入。';
    }
    function makeHandle() {
        if (!moving || busy || pending || !focused || !preview.has(focused)) return;
        const row=rows.find(item => idOf(item)===focused),center=row && centerOf(row); if (!center) return;
        const delta=offsetOf(focused);
        handle=L.marker([center.lat+delta.lat,center.lng+delta.lng],{draggable:true,autoPan:true,bubblingMouseEvents:false,keyboard:true,
            icon:L.divIcon({className:'zdm-move-marker',html:'<span class="zdm-move-handle"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v18M3 12h18m-12-6 3-3 3 3m-6 12 3 3 3-3M6 9l-3 3 3 3m12-6 3 3-3 3"/></svg></span>',iconSize:[42,42],iconAnchor:[21,21]}),title:'微调区域 '+row.code,alt:'拖动以同步微调区域 '+row.code+' 的手绘与 DXF'}).addTo(comparison);
        handle.bindTooltip('拖动微调 '+esc(row.code),{direction:'top',offset:[0,-22],className:'zdm-map-label'});
        handle.on('click',event => { L.DomEvent.stopPropagation(event); });
        handle.on('dragstart',() => {
            gesture={id:focused,before:{...offsetOf(focused)},start:handle.getLatLng(),zoom:bridge.map.getZoom(),mapDragging:bridge.map.dragging.enabled(),moved:false,last:handle.getLatLng()};
            bridge.scopedDragging?.(true); bridge.map.dragging.disable(); bridge.map.getContainer().classList.add('zdm-dragging'); renderActions();
        });
        handle.on('drag',event => {
            if (!gesture) return;
            const point=event.target.getLatLng(),pixels=bridge.map.project(point,gesture.zoom).distanceTo(bridge.map.project(gesture.start,gesture.zoom));
            if (!gesture.moved && pixels<5) return;
            const next={lat:gesture.before.lat+point.lat-gesture.start.lat,lng:gesture.before.lng+point.lng-gesture.start.lng};
            if (Math.abs(next.lat)>0.02 || Math.abs(next.lng)>0.02 || movement(row,next)>1000) { handle.setLatLng(gesture.last); if (el('MoveHint')) el('MoveHint').textContent='微调超过 1 km，请使用整体配准处理大范围位置变化。'; return; }
            gesture.moved=true; gesture.last=point; setOffset(gesture.id,next); paintOffset(gesture.id); renderMoveActions();
        });
        handle.on('dragend',() => {
            if (!gesture) return;
            const current=gesture; gesture=null; restoreMapDrag(current); bridge.map.getContainer().classList.remove('zdm-dragging');
            if (current.moved) {
                const history=undo.get(current.id) || []; history.push(current.before); undo.set(current.id,history.slice(-20));
                selected.add(current.id); row.reviewed=false;
                message('区域 '+row.code+' 已同步微调约 '+movement(row,offsetOf(current.id)).toFixed(1)+' m；仅为预览，请点击保存后生效。');
            } else setOffset(current.id,current.before);
            compare([...preview],false); render();
        });
        bridge.scopedDragging?.(true); bridge.map.getContainer().classList.add('zdm-positioning');
    }
    function setMoving(value) { removeHandle(); moving=!!value && !busy && !pending; if (moving) { bridge.lock(); makeHandle(); } renderMoveActions(); }
    function showAll() {
        setMoving(false); preview.clear(); focused=null; comparison.clearLayers(); layersByZone.clear();centers.clear();
        if (bridge.map.hasLayer(comparison)) bridge.map.removeLayer(comparison);
        bridge.comparison(false); el('Legend').hidden=true;
        el('List').querySelectorAll('.is-focused,.is-active').forEach(row => row.classList.remove('is-focused','is-active')); renderActions();
    }
    function compare(ids, fit) {
        removeHandle(); preview=new Set(ids.map(String)); if (!preview.size) { showAll(); return; }
        if (!preview.has(focused)) focused=[...preview][0];
        bridge.lock(); bridge.comparison(true); comparison.clearLayers(); layersByZone.clear();centers.clear(); comparison.addTo(bridge.map);
        const bounds=L.latLngBounds([]);
        for (const row of rows.filter(item => preview.has(idOf(item)))) {
            const active=idOf(row)===focused,versions=[
                [coordinates(row.dxf_boundary_points),{color:'#e5b560',fillColor:'#e5b560',weight:active ? 3 : 2,dashArray:'3 4',fillOpacity:active ? .19 : .07}],
                [coordinates(row.manual_boundary_points),{color:'#a5d3f2',fillColor:'#5c9fd3',weight:active ? 3 : 2,dashArray:'7 5',fillOpacity:active ? .2 : .07}],
                [usingSaved(row) ? null : bridge.groupBoundary(groupsOf(row)),{color:'#5fd59a',fillColor:'#35bc7c',weight:active ? 3.5 : 2,fillOpacity:active ? .24 : .08}]
            ];
            let labelLayer=null;const layers=[];
            for (const [boundary,style] of versions) {
                if (!boundary?.length) continue;
                const layer=L.polygon(translated(boundary,offsetOf(idOf(row))),{...style,interactive:true,bubblingMouseEvents:false}).addTo(comparison);
                layer.on('click',event => { L.DomEvent.stopPropagation(event); if (busy || pending || gesture) return; focused=idOf(row); compare([...preview],false); render(); });
                layers.push({layer,boundary}); bounds.extend(layer.getBounds()); labelLayer=layer;
            }
            layersByZone.set(idOf(row),layers);
            if (labelLayer) {
                const center=labelLayer.getBounds().getCenter(),delta=offsetOf(idOf(row));
                centers.set(idOf(row),L.latLng(center.lat-delta.lat,center.lng-delta.lng));
                labelLayer.bindTooltip(esc(row.code),{permanent:true,direction:'center',className:'zdm-map-label'});
            }
        }
        el('Legend').hidden=false;
        if (fit && bounds.isValid()) bridge.map.fitBounds(bounds,{padding:[34,34],maxZoom:20});
        makeHandle(); renderActions();
    }
    function restoreOffset(reset) {
        if (busy || pending || gesture || !focused) return;
        const row=rows.find(item => idOf(item)===focused);if (!row) return;
        const history=undo.get(focused) || [];
        if (reset) { offsets.delete(focused);undo.delete(focused); }
        else { if (!history.length) return;setOffset(focused,history.pop());undo.set(focused,history); }
        row.reviewed=false;compare([...preview],false);render();
        message('已'+(reset ? '取消区域 '+row.code+' 的本次微调' : '撤销区域 '+row.code+' 的上次微调')+'，尚未写入服务器。');
    }
    async function post(payload) {
        const body=new FormData();Object.entries(payload).forEach(([key,value]) => body.append(key,value));
        let response;
        try { response=await fetch('',{method:'POST',credentials:'same-origin',headers:{'X-CSRFToken':bridge.csrf()},body}); }
        catch (_) { const error=new Error('网络连接中断，请重试本次操作。');error.uncertain=true;throw error; }
        let data;
        try { data=await response.json(); }
        catch (_) { const error=new Error('未能确认操作结果，请重试本次操作。');error.uncertain=true;throw error; }
        if (!response.ok || !data.success) { const error=new Error(data.message || data.error || '操作未完成，请重试。');error.uncertain=!!data.uncertain || response.status>=500;throw error; }
        return data;
    }
    async function run() {
        if (busy || pending || gesture || !bridge.state().ready) return;
        const version=bridge.state().version,mine=++generation,previous=new Map(rows.map(row => [idOf(row),{groups:groupsOf(row),source:row.editSource}]));
        bridge.lock();showAll();setBusy(true);message('正在比较手绘边界与 CAD 轮廓…');
        try {
            const data=await post({action:'auto_match',transformed_json:JSON.stringify(bridge.state().transformed)});
            if (mine!==generation || version!==bridge.state().version) return;
            token=data.match_token;selected.clear();consumed.clear();saved.clear();
            rows=(data.zones || []).map(row => {
                const candidates=row.candidates || [],old=previous.get(idOf(row));
                const choice=candidates.findIndex(item => JSON.stringify(item.group_ids)===JSON.stringify(old?.groups));
                if (offsets.has(idOf(row))) selected.add(idOf(row));
                return {...row,candidates,choice:Math.max(0,choice),reviewed:false,editSource:old?.source};
            });
            const valid=new Set(rows.map(idOf));for (const id of offsets.keys()) if (!valid.has(id)) { offsets.delete(id);undo.delete(id); }
            bridge.update(rows);
            const count=rows.filter(row => row.high_confidence && !hasDxf(row)).length;
            message('匹配已完成：'+count+' 个可靠新匹配。'+(offsets.size ? offsets.size+' 个未保存微调已保留，请重新对照后保存。' : '请对照后选择保存；已有 DXF 不会自动覆盖。'));
        } catch (error) { if (mine===generation) { token=null;message(error.message,true); } }
        finally { setBusy(false);render(); }
    }
    function updateRows(updated) {
        bridge.update(updated);
        for (const item of updated || []) { const row=rows.find(value => idOf(value)===idOf(item));if (row) Object.assign(row,item); }
    }
    async function execute(attempt,retry) {
        if (busy || gesture) return;
        pending=attempt;setBusy(true);message('正在保存所选区域…');
        try {
            let data;
            if (retry) try { const response=await fetch('/api/submissions/'+attempt.payload.submission_key+'/',{credentials:'same-origin',cache:'no-store'});const receipt=await response.json();if (receipt.found && receipt.result?.success) data=receipt.result; } catch (_) {}
            if (!data) data=await post(attempt.payload);
            pending=null;updateRows(data.zones || []);
            if (attempt.kind==='save') {
                for (const item of attempt.items) item.groups.forEach(group => consumed.set(group,item.id));
                bridge.update([],attempt.items.flatMap(item => item.groups));
            }
            for (const item of attempt.items) {
                const row=rows.find(value => idOf(value)===item.id);
                if (attempt.kind!=='source') { offsets.delete(item.id);undo.delete(item.id);saved.add(item.id);if (row) { row.editSource='existing';row.reviewed=false; } }
                else if (row) row.sourceChanged=true;
                selected.delete(item.id);
            }
            message(data.message || '所选区域已保存。');compare(attempt.items.map(item => item.id),false);
        } catch (error) { if (!error.uncertain) pending=null;message(error.message,true); }
        finally { setBusy(false);render();if (pending) message(el('Status').textContent,true); }
    }
    function save(mode) {
        const items=selectedRows();if (busy || pending || gesture || !items.length || saveProblem(items)) return;
        const translate=items.every(row => operation(row)==='translate');
        const assignments=items.map(row => ({zone_id:row.zone_id || row.id,expected_revision:row.expected_revision,translation:{...offsetOf(idOf(row))},
            ...(translate ? {reviewed:true} : {group_ids:groupsOf(row),reviewed:!!row.reviewed || !needsReview(row),overwrite_existing:hasDxf(row)})}));
        const payload=translate ? {action:'batch_translate',submission_key:crypto.randomUUID(),mode,zones:JSON.stringify(assignments)} :
            {action:'batch_assign',match_token:token,submission_key:crypto.randomUUID(),mode,assignments:JSON.stringify(assignments)};
        execute({kind:translate ? 'translate' : 'save',items:items.map(row => ({id:idOf(row),groups:translate ? [] : [...groupsOf(row)]})),payload});
    }
    function switchSource(source) {
        const items=selectedRows();
        if (busy || pending || gesture || !items.length || items.some(row => shifted(row) || (source==='dxf' ? !hasDxf(row) : !row.manual_boundary_points?.length))) return;
        execute({kind:'source',items:items.map(row => ({id:idOf(row),groups:[]})),payload:{action:'batch_switch_source',source,submission_key:crypto.randomUUID(),
            zones:JSON.stringify(items.map(row => ({zone_id:row.zone_id || row.id,expected_revision:row.expected_revision})))}});
    }
    function invalidate(reason) {
        generation++;token=null;selected.clear();showAll();offsets.clear();undo.clear();rows=baseline();
        message(reason || '位置或配准已改变，请重新计算匹配。');render();
    }
    function focusZone(id,fit=true) { if (busy || pending || gesture) return;id=String(id);if (!rows.some(row => idOf(row)===id)) return;focused=id;compare([id],fit);render(); }
    el('List').addEventListener('click',event => { if (busy || pending) return;const button=event.target.closest('[data-focus]');if (button) focusZone(button.closest('[data-zone]').dataset.zone); });
    el('List').addEventListener('change',event => {
        if (busy || pending) return;
        const card=event.target.closest('[data-zone]'),row=rows.find(item => idOf(item)===card?.dataset.zone);if (!row) return;
        if (event.target.matches('[data-select]')) { event.target.checked ? selected.add(idOf(row)) : selected.delete(idOf(row));focused=event.target.checked ? idOf(row) : focused;compare([...selected],true);render(); }
        else if (event.target.matches('[data-candidate]')) { row.choice=Number(event.target.value);row.reviewed=false;focused=idOf(row);compare(selected.has(focused) ? [...selected] : [focused],true);render();if (shifted(row)) message('候选已切换，本区域的未保存微调已保留，请重新对照。'); }
        else if (event.target.matches('[data-edit-source]')) { row.editSource=event.target.value;row.reviewed=false;focused=idOf(row);compare(selected.has(focused) ? [...selected] : [focused],false);render();if (shifted(row)) message('保存基准已切换，本区域的未保存微调已保留，请重新对照。'); }
        else if (event.target.matches('[data-reviewed]')) { row.reviewed=event.target.checked;renderActions(); }
    });
    ['Search','Filter'].forEach(key => el(key).addEventListener(key==='Search' ? 'input' : 'change',() => { limit=60;render(); }));
    el('Run').onclick=run;el('ShowAll').onclick=showAll;el('More').onclick=() => { limit+=60;render(); };
    el('Clear').onclick=() => { selected.clear();showAll();render(); };
    el('SelectSafe').onclick=() => { filtered().filter(row => !hasDxf(row) && !saved.has(idOf(row)) && !row.sourceChanged && reliable(row) && groupsOf(row).every(group => !consumed.has(group))).forEach(row => selected.add(idOf(row)));compare([...selected],true);render(); };
    el('SelectExisting').onclick=() => { filtered().filter(hasDxf).forEach(row => { row.editSource='existing';selected.add(idOf(row)); });compare([...selected],true);render(); };
    el('Save').onclick=() => save('save_only');el('SaveActive').onclick=() => save('save_and_activate');
    el('Activate').onclick=() => switchSource('dxf');el('Manual').onclick=() => switchSource('manual');
    if (el('Move')) el('Move').onclick=() => setMoving(!moving);
    if (el('Undo')) el('Undo').onclick=() => restoreOffset(false);
    if (el('Reset')) el('Reset').onclick=() => restoreOffset(true);
    window.addEventListener('blur',() => { if (gesture) { setMoving(false);render();message('本次未完成的拖动已取消，之前完成的微调预览保留。'); } });
    window.addEventListener('pagehide',() => setMoving(false));
    document.addEventListener('keydown',event => {
        if (event.key==='Escape' && moving && !busy && !pending) { event.preventDefault();setMoving(false);render();message('已结束微调；已完成的预览位置保留，点击保存后才会写入。'); }
    });
    window.ZoneDxfMatches={invalidate,showAll,focusZone,hasDrafts:() => !!offsets.size,cancelScopedDrag:() => setMoving(false),
        geometryReady(auto) { renderActions();if (auto && bridge.state().ready) run(); },
        legacyUpdated(data) {
            const updated=data.zones || [];updateRows(updated);
            if (!offsets.size) { invalidate('区域边界已更新。已有 DXF 进度已保留，如需继续自动分配请重新匹配。');return; }
            for (const item of updated) { const row=rows.find(value => idOf(value)===idOf(item));if (row) { row.sourceChanged=true;if (hasDxf(row)) row.editSource='existing'; } }
            if (preview.size) compare([...preview],false);
            render();message('区域边界已更新，'+offsets.size+' 个未保存微调预览已保留；更新过的区域请重新对照后保存。');
        }};
    rows=baseline();render();
})();
