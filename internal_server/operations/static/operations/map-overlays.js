/* HD imagery overlays: list rendering, fixed-scale image placement and manager dialog.
   Factory: window.FOSMapOverlays({map, prepareMap}) → {layer, refresh, startCalibration, openManager, destroy} */
(function (root) {
    'use strict';
    function csrfToken() {
        const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : '';
    }
    async function post(url, body) {
        try {
            const response = await fetch(url, {method: 'POST', credentials: 'same-origin', body,
                headers: {'X-CSRFToken': csrfToken(), 'X-Requested-With': 'XMLHttpRequest'}});
            const data = await response.json();
            if (!response.ok) return {success:false, status:response.status, message:data.message || '保存失败，请重试。'};
            return data;
        } catch {
            return {success:false, message:'未收到服务器确认。请检查网络后重试。'};
        }
    }
    async function listOverlays() {
        const response = await fetch('/ops/map-overlays/', {credentials: 'same-origin',
            headers: {'X-Requested-With': 'XMLHttpRequest'}});
        if (!response.ok) return {success: false, overlays: []};
        return response.json();
    }
    // The fourth corner is affine in projected map coordinates, including for rotated images.
    function footprint(map, anchors) {
        const [a, b, c] = [anchors.tl, anchors.tr, anchors.bl].map(ll => map.project(ll, 0));
        const corners = [a, b, c, b.add(c).subtract(a)];
        const bounds = L.bounds(corners);
        // The viewport and image can also be separated along either image edge's normal.
        const axes = [b, c].map(point => {
            const nx = a.y - point.y, ny = point.x - a.x;
            const distances = corners.map(p => p.x * nx + p.y * ny);
            return {nx, ny, min:Math.min(...distances), max:Math.max(...distances)};
        });
        return view => bounds.intersects(view) && axes.every(({nx, ny, min, max}) => {
            const x1 = view.min.x * nx, x2 = view.max.x * nx;
            const y1 = view.min.y * ny, y2 = view.max.y * ny;
            return Math.min(x1, x2) + Math.min(y1, y2) <= max &&
                Math.max(x1, x2) + Math.max(y1, y2) >= min;
        });
    }
    function factory({map, prepareMap}) {
        const controls = document.querySelector('[data-hd-controls]');
        if (!controls) return null;
        const toggle = controls.querySelector('[data-hd-visible]');
        const manage = controls.querySelector('[data-hd-manage]');
        const canManage = !!manage;
        const layer = L.layerGroup().addTo(map);
        const pane = map.getPane('hdImagery') || map.createPane('hdImagery');
        pane.style.zIndex = '250';
        pane.style.pointerEvents = 'none';
        let overlays = [], calibrating = null, dialog = null, disposed = false;
        let revision = 0;

        const rasters = new Map(), footprints = new WeakMap();
        function render() {
            if (disposed) return;
            const visible = new Set();
            const bounds = map.getBounds();
            const view = L.bounds(map.project(bounds.getNorthWest(), 0), map.project(bounds.getSouthEast(), 0));
            for (const item of overlays) {
                if (!toggle.checked || !item.calibrated || !item.active || calibrating) continue;
                if (!footprints.has(item.anchors)) footprints.set(item.anchors, footprint(map, item.anchors));
                if (!footprints.get(item.anchors)(view)) continue;
                visible.add(item.id);
                const {tl, tr, bl} = item.anchors;
                const existing = rasters.get(item.id);
                const key = [tl, tr, bl].join('|');
                if (existing) {
                    if (existing.key !== key) existing.image.reposition(tl, tr, bl);
                    existing.image.setOpacity(item.opacity);
                    existing.key = key;
                } else {
                    const image = L.imageOverlay.rotated(item.image_url, tl, tr, bl,
                        {opacity:item.opacity, interactive:false, pane:'hdImagery', zIndex:item.id}).addTo(layer);
                    rasters.set(item.id, {image, key});
                }
            }
            for (const [id, entry] of rasters) {
                if (visible.has(id)) continue;
                layer.removeLayer(entry.image);
                rasters.delete(id);
            }
        }
        async function refresh() {
            const request = ++revision;
            const data = await listOverlays().catch(() => null);
            if (disposed || request !== revision) return overlays;
            if (data?.success) { overlays = data.overlays; render(); }
            else statusText('影像列表加载失败，请重新打开。');
            return overlays;
        }

        /* ---- calibration: move and rotate the whole image ---- */
        function stopCalibration() {
            if (!calibrating) return;
            const state = calibrating;
            calibrating = null;
            state.cleanup();
            render();
        }
        function validWidth(input) {
            if (!input || input.checkValidity()) return true;
            input.closest('details').open = true;
            input.reportValidity();
            return false;
        }
        function startCalibration(id) {
            if (!canManage || disposed) return;
            const item = overlays.find(entry => entry.id === id);
            if (!item) return;
            const widthInput = dialog?.querySelector('[data-ground-width]');
            if (!item.anchors && !validWidth(widthInput)) return;
            dialog?.close();
            stopCalibration();
            prepareMap?.();
            const container = map.getContainer();
            // Use one fixed Web Mercator coordinate plane for the entire edit.
            const referenceZoom = 19;
            const project = ll => map.project(ll, referenceZoom);
            const unproject = point => map.unproject(point, referenceZoom);
            const saved = item.anchors && ['tl', 'tr', 'bl'].map(key => project(item.anchors[key]));
            let center = saved ? saved[1].add(saved[2]).divideBy(2) : project(map.getCenter());
            const groundWidth = widthInput?.valueAsNumber;
            function sourceOffsets(width, height) {
                if (groundWidth > 0) {
                    const metersPerPixel = map.distance(unproject(center), unproject(center.add([1, 0])));
                    const groundPixels = groundWidth / metersPerPixel;
                    height = groundPixels * height / width;
                    width = groundPixels;
                }
                return [[-1,-1],[1,-1],[-1,1]].map(([x,y]) => L.point(x*width/2,y*height/2));
            }
            let offsets = saved ? saved.map(point => point.subtract(center)) : sourceOffsets(item.width,item.height);
            const direction = point => Math.atan2(point.y, point.x) * 180 / Math.PI;
            const wrap = degrees => {
                const signed = ((degrees + 180) % 360 + 360) % 360 - 180;
                return signed === -180 && degrees > 0 ? 180 : signed;
            };
            const originalAngle = saved ? direction(saved[1].subtract(saved[0])) : 0;
            let angle = originalAngle, points = offsets.map(offset => center.add(offset));
            let loaded = false, positioned = !!item.anchors, saving = false, conflict = false, panOnly = false;
            let gesture = null;
            const listeners = new AbortController();

            const editPane = map.getPane('hdPlacement') || map.createPane('hdPlacement');
            editPane.style.zIndex = '625';
            editPane.style.pointerEvents = 'none';
            const image = L.imageOverlay.rotated(item.image_url, ...points.map(unproject),
                {pane:'hdPlacement', opacity:0.55, interactive:false});
            const grip = L.marker(unproject(center), {pane:'hdPlacement', interactive:false, keyboard:false,
                title:'拖动以旋转影像', icon:L.divIcon({className:'hd-turn-handle', html:'↻',
                    iconSize:[38,38], iconAnchor:[19,19]})});
            const panel = document.createElement('section');
            panel.className = 'hd-align-panel';
            panel.setAttribute('aria-label', '影像校准');
            panel.innerHTML = '<p data-message role="status"></p><div class="hd-adjustments">' +
                '<label>旋转 <input data-angle type="range" min="-180" max="180" step="0.1"><output data-degrees></output></label>' +
                '<label>对照透明度 <input data-mix type="range" min="0" max="100" value="55"><output data-percent>55%</output></label></div>' +
                '<div class="hd-placement-actions"><button type="button" data-pan aria-pressed="false">平移地图</button>' +
                '<button type="button" data-fit>回到影像</button><button type="button" data-cancel>取消</button>' +
                '<button type="button" data-save>保存位置</button></div>';
            const stage = container.parentElement;
            stage.classList.add('hd-calibrating');
            stage.append(panel);
            panel.tabIndex = -1;
            panel.focus({preventScroll:true});
            const el = key => panel.querySelector('[data-'+key+']');
            const message = value => { el('message').textContent = value; };
            function syncControls() {
                el('save').disabled = !loaded || !positioned || saving || conflict || !!gesture;
                el('angle').disabled = !loaded || saving || conflict;
                el('cancel').disabled = saving;
                el('pan').setAttribute('aria-pressed', String(panOnly));
                editPane.classList.toggle('hd-editable', loaded && !panOnly && !saving && !conflict);
            }
            function positionGrip() {
                const top = points[0].add(points[1]).divideBy(2);
                const outward = top.subtract(center);
                const gap = 26 / map.getZoomScale(map.getZoom(), referenceZoom);
                grip.setLatLng(unproject(top.add(outward.multiplyBy(gap / (outward.distanceTo([0,0]) || 1)))));
            }
            function draw() {
                const radians = (angle-originalAngle) * Math.PI/180;
                const cos = Math.cos(radians), sin = Math.sin(radians);
                points = offsets.map(({x,y}) => center.add([x*cos-y*sin, x*sin+y*cos]));
                image.reposition(...points.map(unproject));
                positionGrip();
                el('angle').value = wrap(angle);
                el('degrees').textContent = Number(wrap(angle).toFixed(1))+'°';
                el('angle').setAttribute('aria-valuetext', el('degrees').textContent);
            }
            function fit() {
                const fourth = points[1].add(points[2]).subtract(points[0]);
                const size = map.getSize();
                const panelRoom = Math.min(panel.offsetHeight+20, size.y*0.38);
                map.fitBounds(L.latLngBounds([...points,fourth].map(unproject)), {
                    paddingTopLeft:[24,48], paddingBottomRight:[24,panelRoom], maxZoom:Math.min(22,map.getMaxZoom()), animate:false
                });
            }
            function endGesture(undo = false) {
                if (!gesture) return;
                const previous = gesture;
                gesture = null;
                if (undo) {center = previous.center; angle = previous.angle; draw();}
                else if (previous.moved) positioned = true;
                if (container.hasPointerCapture(previous.id)) container.releasePointerCapture(previous.id);
                if (previous.wasDraggable) map.dragging.enable();
                editPane.classList.remove('hd-dragging');
                syncControls();
            }
            const mapPoint = event => project(map.mouseEventToLatLng(event));
            function begin(event) {
                if (!event.isPrimary) {endGesture(true); return;}
                if (gesture || !loaded || saving || conflict || panOnly || event.button !== 0) return;
                const rotate = grip.getElement().contains(event.target);
                if (!rotate && event.target !== image.getElement().querySelector('img')) return;
                const start = mapPoint(event);
                gesture = {id:event.pointerId, rotate, start, center, angle, moved:false,
                    wasDraggable:map.dragging.enabled(), bearing:direction(start.subtract(center))};
                map.dragging.disable();
                container.setPointerCapture(event.pointerId);
                editPane.classList.add('hd-dragging');
                if (event.pointerType === 'mouse') event.preventDefault();
                syncControls();
            }
            function move(event) {
                if (!gesture || event.pointerId !== gesture.id) return;
                const current = mapPoint(event);
                const delta = current.subtract(gesture.start);
                if (!gesture.moved && delta.distanceTo([0,0])*map.getZoomScale(map.getZoom(),referenceZoom)<2) return;
                gesture.moved = true;
                if (gesture.rotate) angle = wrap(gesture.angle + direction(current.subtract(gesture.center)) - gesture.bearing);
                else center = gesture.center.add(delta);
                draw();
            }
            const listen = (type, fn) => container.addEventListener(type, fn, {capture:true,signal:listeners.signal});
            listen('pointerdown', begin);
            listen('pointermove', move);
            listen('pointerup', event => {if (gesture?.id === event.pointerId) {move(event);endGesture();}});
            listen('pointercancel', event => {if (gesture?.id === event.pointerId) endGesture(true);});
            listen('lostpointercapture', event => {if (gesture?.id === event.pointerId) endGesture(true);});
            const endBeforeZoom = () => endGesture();
            map.on('zoomstart', endBeforeZoom);
            map.on('zoomend', positionGrip);
            // A placement gesture must not also open a zone, popup or work order.
            listen('click', event => {
                if (!event.target.closest('.leaflet-control')) event.stopImmediatePropagation();
            });
            window.addEventListener('blur', endBeforeZoom, {signal:listeners.signal});
            el('fit').onclick = fit;
            el('pan').onclick = () => {panOnly = !panOnly; syncControls();};
            el('mix').oninput = event => {
                image.setOpacity(Number(event.target.value)/100);
                el('percent').textContent = event.target.value+'%';
            };
            el('angle').oninput = event => {
                angle = Number(event.target.value); positioned = true; draw(); syncControls();
            };
            el('cancel').onclick = stopCalibration;
            const state = {id, cleanup() {
                endGesture(); listeners.abort();
                map.off('zoomstart', endBeforeZoom); map.off('zoomend', positionGrip);
                editPane.classList.remove('hd-editable','hd-dragging');
                grip.remove(); image.remove(); panel.remove();
                stage.classList.remove('hd-calibrating');
            }};
            calibrating = state;
            render(); syncControls(); message('正在加载原图…');
            image.on('load', () => {
                if (calibrating !== state) return;
                // The browser applies EXIF orientation when decoding a photo.
                const source = image.getElement().querySelector('img');
                if (!saved && (source.naturalWidth !== item.width || source.naturalHeight !== item.height)) {
                    offsets = sourceOffsets(source.naturalWidth,source.naturalHeight);
                    draw(); fit();
                }
                loaded = true; syncControls();
                message('拖动影像移动，拖动 ↻ 旋转。用滚轮或地图缩放按钮对照细节。');
            });
            image.on('error', () => {
                if (calibrating !== state) return;
                loaded = false; syncControls(); message('原图加载失败，请取消后重新打开。');
            });
            image.addTo(map);
            const rawImage = image.getElement().querySelector('img');
            rawImage.draggable = false; rawImage.classList.add('hd-placement-image');
            grip.addTo(map);
            draw(); fit();
            el('save').onclick = async () => {
                if (el('save').disabled) return;
                saving = true; syncControls();
                const body = new FormData();
                body.set('calibration_version', item.calibration_version);
                points.map(unproject).forEach((ll, index) => {
                    const key = ['tl','tr','bl'][index];
                    body.set(key+'_lat', ll.lat); body.set(key+'_lng', ll.lng);
                });
                const data = await post('/ops/map-overlays/'+id+'/calibrate/', body);
                if (calibrating !== state) return;
                if (!data.success) {
                    saving = false; conflict = data.status === 409;
                    if (conflict) refresh();
                    syncControls(); message(data.message); return;
                }
                ++revision; Object.assign(item,data.overlay); stopCalibration();
            };
        }

        /* ---- manager dialog: upload, visibility, opacity, delete ---- */
        function row(item) {
            const tr = document.createElement('tr');
            const status = item.calibrated
                ? '<span style="color:#2D6A4F">已校准</span>'
                : '<span style="color:#B00020">未校准</span>';
            tr.innerHTML = '<td>' + item.name.replace(/[<>&]/g, '') + '</td><td>' + status + '</td>' +
                '<td><label><input type="checkbox" data-active ' + (item.active ? 'checked' : '') + '>显示</label></td>' +
                '<td><input type="range" min="0.1" max="1" step="0.05" value="' + item.opacity + '" aria-label="影像透明度" data-opacity></td>' +
                '<td><button type="button" class="btn-sm btn-secondary" data-cal>校准</button> ' +
                '<button type="button" class="btn-sm btn-secondary" data-del>删除</button></td>';
            tr.querySelector('[data-active]').onchange = async event => {
                const input = event.target;
                const body = new FormData(); body.set('active', String(input.checked));
                input.disabled = true;
                const data = await post('/ops/map-overlays/' + item.id + '/update/', body);
                input.disabled = false;
                if (data.success) { item.active = data.overlay.active; render(); }
                else { input.checked = item.active; statusText(data.message); }
            };
            tr.querySelector('[data-opacity]').onchange = async event => {
                const input = event.target;
                const body = new FormData(); body.set('opacity', input.value);
                input.disabled = true;
                const data = await post('/ops/map-overlays/' + item.id + '/update/', body);
                input.disabled = false;
                if (data.success) { item.opacity = data.overlay.opacity; render(); }
                else { input.value = item.opacity; statusText(data.message); }
            };
            tr.querySelector('[data-cal]').onclick = () => { startCalibration(item.id); };
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
            dialog.className = 'hd-manager';
            dialog.setAttribute('aria-label','影像叠加管理');
            dialog.innerHTML =
                '<div class="v2-modal-header"><h2>影像叠加管理</h2><button type="button" class="v2-modal-close" data-close aria-label="关闭">×</button></div>' +
                '<div class="v2-modal-body"><p>已校准并启用的影像会显示在灌溉、植保和绿化地图上。</p><div class="op-field"><label>名称<input class="v2-input" data-name placeholder="如：北区高清影像"></label>' +
                '<label>影像文件（JPG/PNG/WebP，≤15MB）<input type="file" accept="image/jpeg,image/png,image/webp" data-file></label>' +
                '<button type="button" class="v2-btn-submit" data-upload>上传</button></div>' +
                '<details class="hd-source-scale"><summary>未校准原图的比例</summary><label>原图地面宽度（米，可选） <input data-ground-width type="number" min="0.01" max="40075017" step="any" placeholder="按底图 19 级像素"></label>' +
                '<p>已知实测宽度时填写。留空按原图每像素对应 19 级底图一像素放置，移动和旋转会保持这个比例。</p></details>' +
                '<p data-status role="status" style="min-height:1.2em"></p>' +
                '<div class="ops-table-wrap"><table class="app-table"><thead><tr><th>名称</th><th>状态</th><th>显示</th><th>透明度</th><th>操作</th></tr></thead><tbody data-overlay-rows></tbody></table></div></div>';
            document.body.append(dialog);
            statusNode = dialog.querySelector('[data-status]');
            dialog.querySelector('[data-close]').onclick = () => dialog.close();
            dialog.querySelector('[data-upload]').onclick = async event => {
                const name = dialog.querySelector('[data-name]').value, file = dialog.querySelector('[data-file]').files[0];
                if (!file) { statusText('请先选择影像文件。'); return; }
                if (!validWidth(dialog.querySelector('[data-ground-width]'))) return;
                const body = new FormData(); body.set('name', name); body.set('image', file);
                event.target.disabled = true; statusText('正在上传…');
                const data = await post('/ops/map-overlays/new/', body);
                event.target.disabled = false;
                statusText(data.message);
                if (data.success) {
                    dialog.querySelector('[data-name]').value = '';
                    dialog.querySelector('[data-file]').value = '';
                    await refresh().then(renderDialog);
                    startCalibration(data.overlay.id);
                }
            };
        }
        function openManager() {
            if (!canManage || calibrating || disposed) return;
            if (!dialog) buildDialog();
            dialog.querySelector('[data-ground-width]').value = '';
            refresh().then(renderDialog).then(() => { if (!disposed && !dialog.open) dialog.showModal(); });
        }

        map.on('moveend resize', render);
        toggle.onchange = render;
        if (manage) manage.onclick = openManager;
        refresh();
        return {layer, refresh, startCalibration, openManager,
                isCalibrating: () => !!calibrating, destroy() { disposed=true; map.off('moveend resize', render); toggle.onchange=null; if(manage) manage.onclick=null; stopCalibration(); layer.remove(); dialog?.remove(); }};
    }
    root.FOSMapOverlays = factory;
})(typeof globalThis !== 'undefined' ? globalThis : this);
