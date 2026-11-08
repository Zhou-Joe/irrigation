(function () {
    'use strict';
    const ready = fn => document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', fn) : fn();
    ready(function () {
        const byId = id => document.getElementById(id);
        const runtime = window.IrrigationMapRuntime;
        const canSubmit = byId('pestCanSubmit').dataset.value === 'yes';
        const map = L.map('map', {preferCanvas:true, zoomControl:false}).setView([31.143,121.658],16);
        window._map = map;
        L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
            maxZoom:22,maxNativeZoom:19,attribution:'Esri'}).addTo(map);
        L.control.zoom({zoomInText:window.uiIcon('plus'),zoomOutText:window.uiIcon('minus')}).addTo(map);
        const groups = Object.fromEntries(['shared','zones','buildings','monitoring','records'].map(k=>[k,L.layerGroup().addTo(map)]));
        let locations=[], recent=[], initialized=false, dirty=false, busy=false, gpsMarker=null;
        const visible = new Set(Object.keys(groups));
        function notice(message) {byId('pestMapNotice').textContent=message;}
        function layerKey(p) {
            if(p.shared) return 'shared';
            if(p.kind==='monitoring') return 'monitoring';
            return ['building','floor','room'].includes(p.kind)?'buildings':'zones';
        }
        function popup(p) {
            const div=document.createElement('div');div.className='pest-place-popup';
            const title=document.createElement('h3');title.textContent=p.name;div.append(title);
            const detail=document.createElement('p');detail.textContent=[p.code,p.kind_label,p.source].filter(Boolean).join(' · ');div.append(detail);
            if(canSubmit) {const button=document.createElement('button');button.textContent='创建工单';button.onclick=()=>openForm([p.id]);div.append(button);}
            return div;
        }
        function focusPlace(p) {
            if(p.center) {map.flyTo([p.center.lat,p.center.lng],19);L.popup().setLatLng(p.center).setContent(popup(p)).openOn(map);}
            else {notice('此地点尚未设置地图位置，可直接选择它创建工单。');if(canSubmit)openForm([p.id]);}
        }
        function render() {
            Object.values(groups).forEach(g=>g.clearLayers());
            const search=byId('zoneSearch').value.trim().toLowerCase();
            const list=byId('pestLocationList');list.replaceChildren();
            const points=[];
            for(const p of locations) {
                if(search&&!((p.name+' '+p.code).toLowerCase().includes(search)))continue;
                const key=layerKey(p);
                if(!visible.has(key))continue;
                const row=document.createElement('button');row.type='button';row.className='pest-location-row';
                const name=document.createElement('strong');name.textContent=p.name;
                const sub=document.createElement('small');sub.textContent=[p.code,p.kind_label,p.shared?'共享地点':'本团队'].filter(Boolean).join(' · ');
                row.append(name,sub);row.onclick=()=>focusPlace(p);list.append(row);
                const color=key==='monitoring'?'#ba741b':key==='buildings'?'#3e75a3':'#2d6a4f';
                const rings=runtime.boundaryRings(p.boundary);
                if(rings.length)for(const ring of rings) {
                    L.polygon(ring,{color,weight:2,fillOpacity:.18}).bindPopup(popup(p)).addTo(groups[key]);points.push(...ring);
                } else if(p.center) {
                    const point=[p.center.lat,p.center.lng];points.push(point);
                    L.circleMarker(point,{radius:key==='monitoring'?7:9,color,fillColor:color,fillOpacity:.85,weight:2})
                        .bindPopup(popup(p)).addTo(groups[key]);
                }
            }
            if(!list.children.length) {const empty=document.createElement('p');empty.textContent='暂无符合条件的地点';empty.style.padding='16px';list.append(empty);}
            if(!initialized&&points.length) {map.fitBounds(L.latLngBounds(points).pad(.2),{maxZoom:18});initialized=true;}
            for(const record of recent) for(const id of record.locations) {
                const p=locations.find(item=>item.id===id);
                if(!p||!p.center)continue;
                const link=document.createElement('a');link.href='/work-reports/'+record.id+'/';link.textContent=record.number+' · '+record.date;
                L.circleMarker(p.center,{radius:5,color:'#69549a',fillOpacity:.9,weight:2}).bindPopup(link).addTo(groups.records);
            }
        }
        async function refresh() {
            try {const data=await runtime.fetchJSON('/api/zones-payload/',{cache:'no-store'});
                if(data.business!=='pest-control') {location.reload();return;}
                locations=data.locations;recent=data.records;render();notice('植保地图 · '+locations.length+' 个授权地点');
            } catch(_) {notice('地图数据加载失败，请刷新重试。');}
        }
        document.querySelectorAll('[data-pest-layer]').forEach(input=>input.addEventListener('change',function(){
            const key=this.dataset.pestLayer;
            if(this.checked) {visible.add(key);map.addLayer(groups[key]);} else {visible.delete(key);map.removeLayer(groups[key]);}
            render();
        }));
        byId('mapLayerToggleBtn').onclick=()=>{byId('mapLayerBody').hidden=!byId('mapLayerBody').hidden;};
        byId('zoneSearch').addEventListener('input',render);
        function toggleSidebar() {
            if(matchMedia('(max-width:768px)').matches)byId('mapContainer').classList.toggle('pest-sidebar-open');
            else {byId('sidebar').classList.toggle('collapsed');byId('mapContainer').classList.toggle('sidebar-collapsed');}
            setTimeout(()=>map.invalidateSize(),200);
        }
        byId('pestSidebarClose').onclick=toggleSidebar;byId('sidebarExpandBtn').onclick=toggleSidebar;
        const locate=L.control({position:'topright'});
        locate.onAdd=function(){const button=L.DomUtil.create('button','locate-btn map-tool-btn');button.type='button';button.title='定位我';button.setAttribute('aria-label','定位我');button.innerHTML=window.uiIcon('pin');L.DomEvent.disableClickPropagation(button);
            button.onclick=async()=>{button.disabled=true;notice('正在定位…');try{if(!navigator.geolocation)throw Error('unavailable');const p=await runtime.requestLocation(navigator.geolocation);if(gpsMarker)map.removeLayer(gpsMarker);gpsMarker=L.marker([p.coords.latitude,p.coords.longitude]).addTo(map);map.flyTo(gpsMarker.getLatLng(),18);notice('已定位，精度约 '+Math.round(p.coords.accuracy)+' 米。');}catch(_){notice('定位未成功，请检查定位权限或手机定位服务。');}finally{button.disabled=false;}};return button;};locate.addTo(map);
        function closeForm(force=false) {
            if(busy)return;
            if(!force&&dirty&&!confirm('尚未提交的工单将关闭，确定继续？'))return;
            byId('woModalContainer').classList.remove('open');
            byId('woModalContainer').hidden=true;byId('woModalBackdrop').hidden=true;dirty=false;
        }
        async function openForm(ids=[]) {
            if(!canSubmit)return;
            byId('woModalContainer').hidden=false;byId('woModalBackdrop').hidden=false;
            byId('woModalContainer').classList.add('open');
            byId('woModalBody').textContent='正在加载植保作业层级…';byId('pestSubmitStatus').textContent='';
            byId('woSubmitBtn').disabled=true;dirty=false;
            try {const response=await fetch('/api/modal/workorder-data/',{credentials:'same-origin',cache:'no-store'});
                const data=await response.json();if(!response.ok)throw Error(data.error||'加载失败');
                byId('woModalBody').innerHTML=data.form_html;
                const form=byId('pestWorkorderForm');
                const tree=JSON.parse(form.querySelector('#pest-work-tree').textContent);
                window.FOSWorkorderChips.mount(form,tree,ids,()=>{dirty=true;});
                form.addEventListener('change',()=>{dirty=true;});form.addEventListener('input',()=>{dirty=true;});
                form.addEventListener('submit',e=>{e.preventDefault();submit();});
                byId('woSubmitBtn').disabled=false;
            } catch(error) {byId('woModalBody').textContent=error.message||'表单加载失败，请重试。';}
        }
        async function submit() {
            const form=byId('pestWorkorderForm');if(busy||!form||!form.reportValidity())return;
            if(!form.querySelector('input[name=locations]')) {byId('pestSubmitStatus').textContent='请选择至少一个作业地点。';return;}
            if(!form.querySelector('input[name=nodes]')) {byId('pestSubmitStatus').textContent='请选择至少一项工作内容。';return;}
            busy=true;byId('woSubmitBtn').disabled=true;byId('pestSubmitStatus').textContent='正在提交…';
            try {const response=await fetch('/mobile/workorder/v2/',{method:'POST',credentials:'same-origin',body:new FormData(form),headers:{'X-Requested-With':'XMLHttpRequest'}});
                const data=await response.json();if(!response.ok||!data.success)throw Error(data.message||'提交失败');
                busy=false;dirty=false;closeForm(true);notice(data.number+' 已提交。');refresh();
            } catch(error) {byId('pestSubmitStatus').textContent=error.message||'网络错误，请保留表单后重试。';}
            finally {busy=false;byId('woSubmitBtn').disabled=false;}
        }
        byId('pestCloseWorkorder').onclick=()=>closeForm();byId('woModalBackdrop').onclick=()=>closeForm();byId('woSubmitBtn').onclick=submit;
        if(byId('pestCreateWorkorder'))byId('pestCreateWorkorder').onclick=()=>openForm();
        document.querySelector('.business-switch')?.addEventListener('submit',e=>{
            if(busy||(dirty&&!confirm('当前工单尚未提交，确定切换团队？'))) {e.preventDefault();return;}
            try {sessionStorage.removeItem('irrigation-tab-navigation-v1');}catch(_){}
        });
        window.quickWorkorder=ids=>openForm(ids);
        window.addEventListener('pageshow',e=>{if(e.persisted)refresh();});
        window.addEventListener('focus',()=>{if(!busy&&!dirty)refresh();});
        refresh();
        if(new URL(location.href).searchParams.get('action')==='workorder')openForm();
    });
})();
