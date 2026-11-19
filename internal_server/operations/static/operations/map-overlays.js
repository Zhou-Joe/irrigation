/* HD imagery overlays: list rendering, three-corner calibration and manager dialog.
   Factory: window.FOSMapOverlays({map, canManage}) → {layer, refresh, startCalibration, openManager, destroy} */
(function (root) {
    'use strict';
    function csrfToken() {
        const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : '';
    }
    async function post(url, body) {
        const response = await fetch(url, {method: 'POST', credentials: 'same-origin', body,
            headers: {'X-CSRFToken': csrfToken(), 'X-Requested-With': 'XMLHttpRequest'}});
        const data = await response.json().catch(() => ({success: false, message: '网络错误，请重试。'}));
        if (!response.ok && !data.message) data.message = '操作未完成，请重试。';
        return data;
    }
    async function listOverlays() {
        const response = await fetch('/ops/map-overlays/', {credentials: 'same-origin',
            headers: {'X-Requested-With': 'XMLHttpRequest'}});
        if (!response.ok) return {success: false, overlays: []};
        return response.json();
    }
    const cornerLabel = text => L.divIcon({className: 'overlay-anchor', html: '<span>' + text + '</span>',
        iconSize: [22, 22], iconAnchor: [11, 11]});
    function factory({map, canManage}) {
        const layer = L.layerGroup().addTo(map);
        let overlays = [], calibrating = null, dialog = null;

        function render() {
            layer.clearLayers();
            overlays.filter(item => item.calibrated && item.active).forEach(item => {
                L.imageOverlay.rotated(item.image_url, item.anchors.tl, item.anchors.tr, item.anchors.bl,
                    {opacity: Math.min(1, Math.max(0.1, item.opacity)), interactive: false}).addTo(layer);
            });
        }
        async function refresh() {
            const data = await listOverlays();
            if (data.success) { overlays = data.overlays; render(); }
            return overlays;
        }

        /* ---- calibration: drag three corner anchors until the image aligns ---- */
        function stopCalibration(saved) {
            const state = calibrating;
            calibrating = null;
            state?.cleanup();
            state?.hint.remove();
            if (!saved) refresh(); else render();
        }
        function startCalibration(id) {
            if (calibrating) stopCalibration(false);
            const item = overlays.find(entry => entry.id === id);
            if (!item) return;
            const bounds = map.getBounds().pad(-0.18);
            let tl = item.anchors?.tl || bounds.getNorthWest(), tr = item.anchors?.tr || bounds.getNorthEast(),
                bl = item.anchors?.bl || bounds.getSouthWest();
            const image = L.imageOverlay.rotated(item.image_url, tl, tr, bl, {opacity: 1, interactive: false}).addTo(map);
            const corner = (label, position) => L.marker(position, {draggable: true, icon: cornerLabel(label),
                zIndexOffset: 1000}).addTo(map);
            const mTl = corner('左上', tl), mTr = corner('右上', tr), mBl = corner('左下', bl);
            const sync = () => image.reposition(mTl.getLatLng(), mTr.getLatLng(), mBl.getLatLng());
            [mTl, mTr, mBl].forEach(marker => marker.on('drag', sync));
            if (item.anchors) map.fitBounds(L.latLngBounds([tl, tr, bl]).pad(0.4));
            const hint = document.createElement('div');
            hint.className = 'pest-map-notice overlay-calibrate-hint';
            hint.setAttribute('role', 'status');
            hint.innerHTML = '拖动三个角点，让影像与底图对齐（支持旋转），然后保存。<button type="button" class="v2-act-btn v2-act-confirm" data-save>保存校准</button><button type="button" class="v2-act-btn v2-act-cancel" data-cancel>取消</button>';
            (map.getContainer().closest('.map-container') || map.getContainer().parentElement || document.body).appendChild(hint);
            calibrating = {id: item.id, hint,
                cleanup: () => {map.removeLayer(image); map.removeLayer(mTl); map.removeLayer(mTr); map.removeLayer(mBl);}};
            hint.querySelector('[data-save]').onclick = async () => {
                const save = [mTl.getLatLng(), mTr.getLatLng(), mBl.getLatLng()];
                const body = new FormData();
                body.set('tl_lat', save[0].lat); body.set('tl_lng', save[0].lng);
                body.set('tr_lat', save[1].lat); body.set('tr_lng', save[1].lng);
                body.set('bl_lat', save[2].lat); body.set('bl_lng', save[2].lng);
                hint.querySelectorAll('button').forEach(button => button.disabled = true);
                const data = await post('/ops/map-overlays/' + item.id + '/calibrate/', body);
                hint.querySelectorAll('button').forEach(button => button.disabled = false);
                if (!data.success) { hint.firstChild.textContent = data.message + ' '; return; }
                stopCalibration(true);
                await refresh();
            };
            hint.querySelector('[data-cancel]').onclick = () => stopCalibration(false);
        }

        /* ---- manager dialog: upload, visibility, opacity, delete ---- */
        function row(item) {
            const tr = document.createElement('tr');
            const status = item.calibrated
                ? '<span style="color:#2D6A4F">已校准</span>'
                : '<span style="color:#B00020">未校准</span>';
            tr.innerHTML = '<td>' + item.name.replace(/[<>&]/g, '') + '</td><td>' + status + '</td>' +
                '<td><label><input type="checkbox" data-active ' + (item.active ? 'checked' : '') + '>显示</label></td>' +
                '<td><input type="range" min="0.1" max="1" step="0.05" value="' + item.opacity + '" data-opacity></td>' +
                '<td><button type="button" class="btn-sm btn-secondary" data-cal>校准</button> ' +
                '<button type="button" class="btn-sm btn-secondary" data-del>删除</button></td>';
            tr.querySelector('[data-active]').onchange = async event => {
                const body = new FormData(); body.set('active', String(event.target.checked));
                const data = await post('/ops/map-overlays/' + item.id + '/update/', body);
                if (data.success) { item.active = data.overlay.active; render(); } else statusText(data.message);
            };
            let opacityTimer = null;
            tr.querySelector('[data-opacity]').oninput = async event => {
                clearTimeout(opacityTimer);
                const value = event.target.value;
                opacityTimer = setTimeout(async () => {
                    const body = new FormData(); body.set('opacity', value);
                    const data = await post('/ops/map-overlays/' + item.id + '/update/', body);
                    if (data.success) { item.opacity = data.overlay.opacity; render(); } else statusText(data.message);
                }, 400);
            };
            tr.querySelector('[data-cal]').onclick = () => { dialog.close(); startCalibration(item.id); };
            tr.querySelector('[data-del]').onclick = async () => {
                if (!confirm('确定删除「' + item.name + '」？')) return;
                const data = await post('/ops/map-overlays/' + item.id + '/delete/', new FormData());
                statusText(data.message);
                if (data.success) await refresh().then(renderDialog);
            };
            return tr;
        }
        let statusNode = null;
        const statusText = message => { if (statusNode) statusNode.textContent = message; };
        async function renderDialog() {
            const tbody = dialog.querySelector('[data-overlay-rows]');
            tbody.replaceChildren(...overlays.map(row));
            if (!overlays.length) {
                const empty = document.createElement('tr');
                empty.innerHTML = '<td colspan="5" style="text-align:center;color:#999">还没有上传影像</td>';
                tbody.append(empty);
            }
        }
        function buildDialog() {
            dialog = document.createElement('dialog');
            dialog.className = 'v2-modal-container';
            dialog.style.maxWidth = '560px';
            dialog.innerHTML =
                '<div class="v2-modal-header"><h2>影像叠加管理</h2><button type="button" class="v2-modal-close" data-close aria-label="关闭">×</button></div>' +
                '<div class="v2-modal-body"><div class="op-field"><label>名称<input class="v2-input" data-name placeholder="如：北区高清影像"></label>' +
                '<label>影像文件（JPG/PNG/WebP，≤15MB）<input type="file" accept="image/jpeg,image/png,image/webp" data-file></label>' +
                '<button type="button" class="v2-btn-submit" data-upload>上传</button></div>' +
                '<p data-status role="status" style="min-height:1.2em"></p>' +
                '<div class="ops-table-wrap"><table class="app-table"><thead><tr><th>名称</th><th>状态</th><th>显示</th><th>透明度</th><th>操作</th></tr></thead><tbody data-overlay-rows></tbody></table></div></div>';
            document.body.append(dialog);
            statusNode = dialog.querySelector('[data-status]');
            dialog.querySelector('[data-close]').onclick = () => dialog.close();
            dialog.querySelector('[data-upload]').onclick = async event => {
                const name = dialog.querySelector('[data-name]').value, file = dialog.querySelector('[data-file]').files[0];
                if (!file) { statusText('请先选择影像文件。'); return; }
                const body = new FormData(); body.set('name', name); body.set('image', file);
                event.target.disabled = true; statusText('正在上传…');
                const data = await post('/ops/map-overlays/new/', body);
                event.target.disabled = false;
                statusText(data.message);
                if (data.success) {
                    dialog.querySelector('[data-name]').value = '';
                    dialog.querySelector('[data-file]').value = '';
                    await refresh().then(renderDialog);
                    dialog.close();
                    startCalibration(data.overlay.id);
                }
            };
            dialog.addEventListener('close', () => { if (calibrating) stopCalibration(false); });
        }
        function openManager() {
            if (!dialog) buildDialog();
            refresh().then(renderDialog).then(() => dialog.showModal());
        }

        refresh();
        return {layer, refresh, startCalibration, openManager,
                destroy() { stopCalibration(false); layer.remove(); dialog?.remove(); }};
    }
    root.FOSMapOverlays = factory;
})(typeof globalThis !== 'undefined' ? globalThis : this);
