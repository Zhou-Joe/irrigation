/* HD imagery overlays: list rendering, three-corner calibration and manager dialog.
   Factory: window.FOSMapOverlays({map, canManage}) → {layer, refresh, startCalibration, openManager, destroy} */
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
            if (!response.ok) return {success:false, message:data.message || '保存失败，请重试。'};
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
    const cornerLabel = text => L.divIcon({className: 'overlay-anchor', html: '<span>' + text + '</span>',
        iconSize: [30, 30], iconAnchor: [15, 15]});
    function factory({map, canManage}) {
        const layer = L.layerGroup().addTo(map);
        const pane = map.getPane('hdImagery') || map.createPane('hdImagery');
        pane.style.zIndex = '250';
        pane.style.pointerEvents = 'none';
        let overlays = [], calibrating = null, dialog = null, disposed = false;
        let revision = 0;

        function render() {
            layer.clearLayers();
            overlays.filter(item => item.calibrated && item.active && item.id !== calibrating?.id).forEach(item => {
                L.imageOverlay.rotated(item.image_url, item.anchors.tl, item.anchors.tr, item.anchors.bl,
                    {opacity: item.opacity, interactive: false, pane:'hdImagery'}).addTo(layer);
            });
        }
        async function refresh() {
            const request = ++revision;
            const data = await listOverlays().catch(() => null);
            if (disposed || request !== revision) return overlays;
            if (data?.success) { overlays = data.overlays; render(); }
            else statusText('影像列表加载失败，请重新打开。');
            return overlays;
        }

        /* ---- calibration: drag three corner anchors until the image aligns ---- */
        function stopCalibration() {
            if (!calibrating) return;
            const state = calibrating;
            calibrating = null;
            state.cleanup();
            render();
        }
        function defaultAnchors(item) {
            const size = map.getSize();
            const scale = Math.min(size.x * .64 / item.width, size.y * .45 / item.height);
            const dx = item.width * scale / 2, dy = item.height * scale / 2;
            const corner = (x,y) => map.containerPointToLatLng([size.x/2+x,size.y*.44+y]);
            return [corner(-dx,-dy),corner(dx,-dy),corner(-dx,dy)];
        }
        function startCalibration(id) {
            if (!canManage || disposed) return;
            stopCalibration();
            const item = overlays.find(entry => entry.id === id);
            if (!item) return;
            const drawer = document.getElementById('mobileOverlay');
            if (drawer?.classList.contains('visible')) document.getElementById('pestSidebarClose')?.click();
            const controls = document.getElementById('mapLayerBody');
            if (controls) controls.hidden = true;
            const existing = item.anchors;
            const points = existing ? [existing.tl,existing.tr,existing.bl] : defaultAnchors(item);
            const image = L.imageOverlay.rotated(item.image_url,...points,{opacity:.55,interactive:false,pane:'hdImagery'});
            const handles = points.map((p,i) => L.marker(p,{draggable:true,
                title:['左上','右上','左下'][i],icon:cornerLabel(['左上','右上','左下'][i]),zIndexOffset:1000}));
            const preview = L.layerGroup([image,...handles]);
            const zoomToImage = () => {
                const [a,b,c] = handles.map(m => map.project(m.getLatLng(),19));
                const fourth = map.unproject(b.add(c).subtract(a),19);
                map.fitBounds(L.latLngBounds([...handles.map(m=>m.getLatLng()),fourth]),{padding:[54,54],animate:false,maxZoom:22});
            };
            if (existing) zoomToImage();
            handles.forEach(m => m.on('drag',()=>image.reposition(...handles.map(h=>h.getLatLng()))));
            const host = map.getContainer().parentElement;
            const hint = document.createElement('section');
            hint.className = 'hd-align-panel';
            hint.setAttribute('aria-label','影像校准');
            hint.innerHTML = '<p data-message role="status"></p><div data-tools><label>对照透明度 <input data-mix type="range" min="0" max="1" step=".05" value=".55"></label><button type="button" data-pairs>用三个地标对齐</button><button type="button" data-save>保存校准</button></div><button type="button" data-ground hidden>确认十字位置</button><button type="button" data-cancel>取消</button>';
            host.append(hint);
            const el = key => hint.querySelector('[data-'+key+']');
            const message = text => {el('message').textContent=text;};
            const ready = () => message('拖动左上、右上和左下角，或用原图与底图上相同的三个地标对齐。');
            const cross = document.createElement('span');
            cross.className = 'hd-align-cross'; cross.hidden = true; cross.setAttribute('aria-hidden','true');
            map.getContainer().append(cross);
            const picker = document.createElement('dialog');
            picker.className = 'hd-point-dialog'; picker.setAttribute('aria-label','选取原图地标');
            picker.innerHTML = '<p data-prompt></p><div class="hd-point-image"><img alt="待校准的原始高清影像"></div><button type="button" data-back>返回角点校准</button>';
            const photo = picker.querySelector('img');
            photo.src = item.image_url;
            document.body.append(picker);
            const marks = [], ground = [];
            function restore() {
                if (picker.open) picker.close();
                cross.hidden=true; el('ground').hidden=true; el('tools').hidden=false;
                preview.addTo(map);ready();
            }
            function chooseImagePoint() {
                picker.querySelector('[data-prompt]').textContent = '请选择第 '+(marks.length+1)+' 个地标，例如路口或建筑拐角。三个点应分散在图上。';
                if (!picker.open) picker.showModal();
            }
            el('pairs').onclick=()=>{
                marks.length=0; ground.length=0;
                picker.querySelectorAll('.hd-point-label').forEach(n=>n.remove());
                preview.remove();el('tools').hidden=true;chooseImagePoint();
            };
            photo.onclick = event => {
                const r=photo.getBoundingClientRect();
                const pt=L.point((event.clientX-r.left)/r.width,(event.clientY-r.top)/r.height);
                if (marks.length===2 && Math.abs(determinant(marks[1].subtract(marks[0]),pt.subtract(marks[0])))<.005) {
                    picker.querySelector('[data-prompt]').textContent='三个地标过于接近或在同一直线上，请换一个点。';return;
                }
                marks.push(pt);
                const label=document.createElement('span');label.className='hd-point-label';
                label.style.left=(100*pt.x)+'%';label.style.top=(100*pt.y)+'%';label.textContent=marks.length;
                photo.parentElement.append(label);
                picker.close();cross.hidden=false;el('ground').hidden=false;
                message('平移、放大底图，让十字对准原图第 '+marks.length+' 个地标，然后确认。');
            };
            const determinant = (a,b) => a.x*b.y-a.y*b.x;
            el('ground').onclick = () => {
                const xy = map.project(map.containerPointToLatLng(map.getSize().divideBy(2)),19);
                if(ground.length===2){
                    const a=ground[1].subtract(ground[0]),b=xy.subtract(ground[0]);
                    if (Math.abs(determinant(a,b)) < Math.max(1,.01*a.distanceTo([0,0])*b.distanceTo([0,0]))) {
                        message('底图上的三个位置过近或接近直线，请重新定位第三个点。');return;
                    }
                }
                ground.push(xy);
                cross.hidden=true;el('ground').hidden=true;
                if(ground.length<3){chooseImagePoint();return;}
                // Affine fit in the same projected plane Leaflet uses to render the image.
                const u=marks[1].subtract(marks[0]),v=marks[2].subtract(marks[0]),den=determinant(u,v);
                const dx=ground[1].subtract(ground[0]),dy=ground[2].subtract(ground[0]);
                const corners=[[0,0],[1,0],[0,1]].map(corner=>{
                    const p=L.point(corner).subtract(marks[0]);
                    return map.unproject(ground[0].add(dx.multiplyBy(determinant(p,v)/den)).add(dy.multiplyBy(determinant(u,p)/den)),19);
                });
                handles.forEach((h,i)=>h.setLatLng(corners[i]));image.reposition(...corners);
                restore();zoomToImage();message('三个地标已对齐。拖动透明度对照道路和屋角，确认后保存。');
            };
            picker.querySelector('[data-back]').onclick=restore;
            picker.oncancel=event=>{event.preventDefault();restore();};
            el('mix').oninput=()=>image.setOpacity(Number(el('mix').value));
            el('cancel').onclick=stopCalibration;
            const state={id:item.id,cleanup(){
                preview.remove();hint.remove();cross.remove();picker.remove();
            }};
            calibrating=state;render();ready();
            image.on('error',()=>{if(calibrating===state){message('高清影像未能加载，请取消并重新打开。');el('save').disabled=true;}});
            preview.addTo(map);
            el('save').onclick=async()=>{
                const body=new FormData();
                ['tl','tr','bl'].forEach((key,i)=>{
                    const p=handles[i].getLatLng();body.set(key+'_lat',p.lat);body.set(key+'_lng',p.lng);
                });
                hint.querySelectorAll('button,input').forEach(b=>b.disabled=true);
                const data=await post('/ops/map-overlays/'+id+'/calibrate/',body);
                if(calibrating!==state)return;
                if(!data.success){hint.querySelectorAll('button,input').forEach(b=>b.disabled=false);message(data.message);return;}
                ++revision;
                Object.assign(item,data.overlay);stopCalibration();
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
            dialog.className = 'hd-manager';
            dialog.setAttribute('aria-label','影像叠加管理');
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
            // Closing the manager starts calibration. Its asynchronous close event must not cancel it.
        }
        function openManager() {
            if (!canManage || calibrating || disposed) return;
            if (!dialog) buildDialog();
            refresh().then(renderDialog).then(() => { if (!disposed && !dialog.open) dialog.showModal(); });
        }

        refresh();
        return {layer, refresh, startCalibration, openManager,
                isCalibrating: () => !!calibrating, destroy() { disposed=true; stopCalibration(); layer.remove(); dialog?.remove(); }};
    }
    root.FOSMapOverlays = factory;
})(typeof globalThis !== 'undefined' ? globalThis : this);
