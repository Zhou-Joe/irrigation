(function () {
    'use strict';
    const ready=fn=>document.readyState==='loading'?document.addEventListener('DOMContentLoaded',fn,{once:true}):fn();
    ready(function () {
        const effects=window.FOSScopedEffects(),byId=id=>document.getElementById(id),runtime=window.IrrigationMapRuntime,markers=window.FOSMapMarkers;
        let canSubmit=byId('pestCanSubmit').dataset.value==='yes',canManage=byId('pestCanSubmit').dataset.manager==='yes',canCreate=byId('pestCanSubmit').dataset.create==='yes';
        const initial=window.FOSMapInitialView;
        const park=runtime.parkView();
        const map=L.map('map',{preferCanvas:true,zoomControl:false,maxBounds:park.bounds,maxBoundsViscosity:park.maxBoundsViscosity,minZoom:park.minZoom,maxZoom:park.maxZoom})
            .setView(runtime.withinPark(initial?.center)?initial.center:park.center,Math.max(park.minZoom,Math.min(park.maxZoom,initial?.zoom||16)));
        window._map=map;markers.enableLabels(map);
        L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:22,maxNativeZoom:19,attribution:'Esri'}).addTo(map);
        L.control.zoom({zoomInText:window.uiIcon('plus'),zoomOutText:window.uiIcon('minus')}).addTo(map);
        const groups=Object.fromEntries(['shared','zones','buildings','monitoring','traps','beehives','records'].map(k=>[k,L.layerGroup().addTo(map)]));
        const overlays=window.FOSMapOverlays?window.FOSMapOverlays({map,canManage}):null;
        if(overlays)groups.overlays=overlays.layer;
        const updateWatermarks = window.FOSMapGeography.watermarks(map, window.MAP_STYLE_CONFIG?.label?.fontSize || 25);
        let views, selectedId = null;
        const visible=new Set(Object.keys(groups));let locations=[],recent=[],initialized=!!initial,dirty=false,busy=false,picker=null,media=null,parameters=null,picking=false,gpsMarker=null,formGeneration=0;
        const shapes=new Map();
        const notice=message=>{const el=byId('pestMapNotice');if(el)el.textContent=message;};
        const equipmentLayer=p=>p.kind==='trap_cage'?'traps':p.kind==='beehive'?'beehives':null;
        const layerKey=p=>p.shared?'shared':equipmentLayer(p)|| (p.kind==='monitoring'?'monitoring':['building','floor','room'].includes(p.kind)?'buildings':'zones');
        function changed(){parameters?.sync();dirty=true;window.IrrigationPWA?.markDirty();}
        function actions(){return [...(canSubmit?[{icon:'clipboard',label:'工单提交',action:()=>openForm()}]:[]),...(canCreate?[{icon:'plus',label:'新增地点/设施',action:()=>creator.open()}]:[]),...(canManage?[{icon:'layers',label:'区域管理',url:'/ops/locations/'}]:[]),{icon:'folder',label:'历史记录',url:'/work-reports/'}];}
        function popup(p){const div=document.createElement('div');div.className='pest-place-popup';const title=document.createElement('h3');title.textContent=p.name;const detail=document.createElement('p');detail.textContent=[p.code,p.kind_label,p.source].filter(Boolean).join(' · ');div.append(title,detail);if(canSubmit){const button=document.createElement('button');button.textContent='创建工单';button.onclick=()=>openForm([p.id]);div.append(button);}return div;}
        function selectStyle() {
            for (const [id, layers] of shapes) {
                const active = picking ? picker?.state.has(id) : id === selectedId;
                for (const layer of layers) {
                    layer.setStyle?.({weight: active ? 4 : 2, fillOpacity: active ? .35 : .18});
                    layer.getElement?.()?.classList.toggle('op-location-pin-selected', !!active);
                }
            }
        }
        function pick(p){picker.state.toggle(p.id);picker.sync();changed();selectStyle();byId('pestPickInfo').textContent=`已选 ${picker.state.selected().length} 个地点`;}
        function focus(place, row) {
            const shape = views.shapes.get(place.id);
            if (creator.active()) {
                if (runtime.withinPark(shape?.center)) {
                    const [lat, lng] = shape.center;
                    map.panTo([lat, lng]);
                    creator.pick({lat, lng});
                    revealMap();
                } else notice(place.name + '尚未标注坐标，请在地图上选点。');
                return;
            }
            if (picking) { pick(place); return; }
            selectedId = place.id;
            byId('pestLocationList').querySelector('[aria-current]')?.removeAttribute('aria-current');
            row.setAttribute('aria-current', 'location');
            selectStyle();
            revealMap();
            map.closePopup();
            map.stop();
            const view = views.target(place);
            if (!view) { notice(place.name + '尚未标注坐标，暂无可定位的区域。'); return; }
            const bounds = L.latLngBounds(view.points);
            const options = {maxZoom: view.maxZoom, padding: [28, 28], animate: false};
            window.FOSMapGeography.afterZoom(map, () => {
                if (effects.stopped || selectedId !== place.id) return;
                if (bounds.getNorthEast().equals(bounds.getSouthWest())) map.setView(bounds.getCenter(), view.maxZoom, options);
                else map.fitBounds(bounds, options);
            });
            notice(view.reference ? place.name + '尚无独立坐标，已显示' + view.reference + '的参考范围。' : '已定位到' + place.name);
        }
        function render(){
            Object.values(groups).forEach(group=>group.clearLayers());shapes.clear();
            const q=byId('zoneSearch').value.trim().toLowerCase(),kind=byId('pestMapKind').value,list=byId('pestLocationList');list.replaceChildren();const points=[];
            for(const p of locations){if(q&&!(p.name+' '+p.code).toLowerCase().includes(q)||kind&&p.kind!==kind)continue;const key=layerKey(p),equipment=equipmentLayer(p);if(!visible.has(key)||(equipment&&!visible.has(equipment)))continue;
                const shape = views.shapes.get(p.id), rings = shape.rings, layers = [];
                const row = document.createElement('button');
                row.type = 'button';
                row.className = 'pest-location-row';
                const symbol = document.createElement('span');
                symbol.className = 'op-kind-icon';
                symbol.style.color = markers.descriptor(p.kind).color;
                symbol.append(markers.glyph(p.kind));
                const name = document.createElement('strong'), sub = document.createElement('small');
                name.textContent = p.name;
                const unplaced = shape.mode !== 'boundary' && !runtime.withinPark(shape.center);
                sub.textContent = [p.code, p.kind_label, p.shared ? '共享地点' : '本团队', unplaced ? '待补坐标' : '']
                    .filter(Boolean).join(' · ');
                row.append(symbol, name, sub);
                if (p.id === selectedId) row.setAttribute('aria-current', 'location');
                row.onclick = () => focus(p, row);
                list.append(row);
                if(shape.mode==='boundary')for(const ring of rings){layers.push(L.polygon(ring,{color:markers.descriptor(p.kind).color,weight:2,fillOpacity:.18}).addTo(groups[key]));points.push(...ring);}
                else if(shape.mode==='pin'&&runtime.withinPark(shape.center)){layers.push(markers.marker(L,p,shape.center).addTo(groups[key]));points.push(shape.center);}
                for(const layer of layers)layer.on('click',event=>{if(creator.pick(event.latlng)){L.DomEvent.stopPropagation(event);return;}if(picking){L.DomEvent.stopPropagation(event);pick(p);}else L.popup().setLatLng(event.latlng||p.center).setContent(popup(p)).openOn(map);});shapes.set(p.id,layers);
            }
            if(!list.children.length){const empty=document.createElement('p');empty.textContent='暂无符合条件的地点';list.append(empty);}
            byId('zoneCount').textContent=locations.length+' 个地点';
            if(!initialized&&points.length){map.fitBounds(L.latLngBounds(points).pad(.2),{maxZoom:18,animate:false});initialized=true;}
            for(const record of recent)for(const id of record.locations){const p=locations.find(item=>item.id===id);if(!runtime.withinPark(p?.center)||!shapes.has(id))continue;const link=document.createElement('a');link.href='/work-reports/'+record.id+'/';link.textContent=record.number+' · '+record.date;L.circleMarker(p.center,{radius:5,color:'#69549a',fillOpacity:.9,weight:2}).bindPopup(link).addTo(groups.records);}
            selectStyle();
        }
        let geography = {}, refreshId = 0;
        async function refresh() {
            const request = ++refreshId;
            try {
                const data = await runtime.fetchJSON('/api/zones-payload/', {cache:'no-store'});
                if (effects.stopped || request !== refreshId) return;
                if (data.business !== 'pest-control') {
                    notice('当前团队已变化，请使用顶部视图选择更新。');
                    return;
                }
                const badge = document.querySelector('.top-nav-notif[href*="tab=tasks"] .notif-count');
                if (badge) {
                    badge.textContent = data.pending_tasks > 99 ? '99+' : String(data.pending_tasks || 0);
                    badge.classList.toggle('show', !!data.pending_tasks);
                }
                locations = data.locations;
                recent = data.records;
                geography = {region_labels:data.region_labels, area_labels:data.area_labels};
                views = window.FOSMapGeography.pestViews(locations, geography);
                updateWatermarks(geography);
                render();
                if (!selectedId) notice('植保地图 · ' + locations.length + ' 个授权地点');
            } catch (error) {
                if (!effects.stopped && request === refreshId) notice('地图数据暂不可用，请重试。');
            }
        }
        const creator=window.FOSMapLocationCreate.mount({map,panel:byId('mapLocationCreate'),markers,L,
            onOpen(){if(!closeForm())return false;initialized=true;byId('zoneSearch').value='';byId('pestMapKind').value='';render();},
            async onSaved(item){const key=layerKey(item);visible.add(key);map.addLayer(groups[key]);const checkbox=document.querySelector('[data-pest-layer="'+key+'"]');if(checkbox)checkbox.checked=true;locations=locations.filter(p=>p.id!==item.id).concat({...item,kind_label:markers.descriptor(item.kind).label,map_display:'pin',boundary:[],center:[Number(item.latitude),Number(item.longitude)],shared:false,source:'图钉标注'});views=window.FOSMapGeography.pestViews(locations,geography);render();await refresh();}});
        map.on('click',event=>creator.pick(event.latlng));
        document.querySelectorAll('[data-pest-layer]').forEach(input=>input.onchange=()=>{const key=input.dataset.pestLayer;if(input.checked){visible.add(key);map.addLayer(groups[key]);}else{visible.delete(key);map.removeLayer(groups[key]);}render();});
        byId('mapLayerToggleBtn').onclick=()=>{const el=byId('mapLayerBody');el.hidden=!el.hidden;};
        byId('filterToggleBtn').onclick=()=>{const el=byId('pestFilterPanel');el.hidden=!el.hidden;};
        byId('pestMapKind').onchange=render;byId('zoneSearch').oninput=render;
        const phone = matchMedia('(max-width:768px)');
        function setSidebar(open, moveFocus = false) {
            const sidebar = byId('sidebar'), trigger = byId('sidebarExpandBtn');
            sidebar.classList.toggle('collapsed', !open);
            sidebar.inert = !open;
            trigger.classList.toggle('visible', !open);
            trigger.setAttribute('aria-expanded', String(open));
            byId('mobileOverlay').classList.toggle('visible', open && phone.matches);
            if (moveFocus) (open ? byId('pestSidebarClose') : trigger).focus({preventScroll:true});
            effects.timeout(() => map.invalidateSize(), 300);
        }
        function revealMap() {
            if (phone.matches && !byId('sidebar').inert) setSidebar(false, true);
        }
        byId('pestSidebarClose').onclick = () => setSidebar(false, true);
        byId('sidebarExpandBtn').onclick = () => setSidebar(true, true);
        byId('mobileOverlay').onclick = () => setSidebar(false, true);
        effects.listen(phone, 'change', () => setSidebar(!phone.matches));
        effects.listen(byId('sidebar'), 'keydown', event => {
            if (event.key === 'Escape') setSidebar(false, true);
        });
        setSidebar(!phone.matches);
        const locate=L.control({position:'topright'});locate.onAdd=()=>{const button=L.DomUtil.create('button','locate-btn map-tool-btn');button.type='button';button.title='定位我';button.innerHTML=window.uiIcon('pin');L.DomEvent.disableClickPropagation(button);button.onclick=async()=>{button.disabled=true;notice('正在定位…');try{const p=await runtime.requestLocation(navigator.geolocation);if(effects.stopped)return;if(!runtime.withinPark([p.coords.latitude,p.coords.longitude])){notice('当前位置在地图显示范围外。');return;}if(gpsMarker)map.removeLayer(gpsMarker);gpsMarker=L.marker([p.coords.latitude,p.coords.longitude]).addTo(map);map.flyTo(gpsMarker.getLatLng(),18);notice('已定位，精度约 '+Math.round(p.coords.accuracy)+' 米。');}catch(_){notice('定位未成功，请检查定位权限或手机定位服务。');}finally{button.disabled=false;}};return button;};locate.addTo(map);
        window.FOSMapActions.mount(actions());
        const legend=document.createElement('div');legend.className='op-marker-legend';legend.setAttribute('aria-label','图钉类型');for(const kind of markers.kinds||['zone','building','floor','room','monitoring','trap_cage','beehive','other']){const item=document.createElement('span'),icon=markers.glyph(kind);icon.style.color=markers.descriptor(kind).color;item.append(icon,document.createTextNode(markers.descriptor(kind).label));legend.append(item);}byId('mapLayerBody').append(legend);
        function finishPick(){picking=false;byId('pestPickActions').hidden=true;byId('pestPickInfo').hidden=true;byId('woModalContainer').hidden=false;byId('woModalBackdrop').hidden=false;picker?.sync();selectStyle();}
        function enterMap(){picking=true;picker.close();byId('woModalContainer').hidden=true;byId('woModalBackdrop').hidden=true;byId('pestPickActions').hidden=false;byId('pestPickInfo').hidden=false;byId('pestPickInfo').textContent=`已选 ${picker.state.selected().length} 个地点`;map.closePopup();selectStyle();}
        byId('pestPickDone').onclick=finishPick;byId('pestPickList').onclick=()=>{finishPick();picker.open();};byId('pestPickClear').onclick=()=>{picker.state.clear();picker.sync();changed();selectStyle();byId('pestPickInfo').textContent='已选 0 个地点';};
        function closeForm(){if(busy)return false;formGeneration++;picking=false;picker?.destroy();picker=null;media?.destroy();media=null;parameters?.destroy();parameters=null;byId('pestPickActions').hidden=true;byId('pestPickInfo').hidden=true;byId('woModalContainer').hidden=true;byId('woModalContainer').classList.remove('open');byId('woModalBackdrop').hidden=true;dirty=false;window.IrrigationPWA?.markClean();selectStyle();return true;}
        async function openForm(ids=[],source={}){if(!canSubmit||busy||creator.busy())return;creator.close();if(picker&&!closeForm())return;const generation=++formGeneration;const container=byId('woModalContainer');container.hidden=false;container.classList.add('open');byId('woModalBackdrop').hidden=false;byId('woModalBody').textContent='正在加载作业内容…';byId('woSubmitBtn').disabled=true;byId('pestSubmitStatus').textContent='';dirty=false;
            try{const response=await fetch('/api/modal/workorder-data/?'+new URLSearchParams(source),{credentials:'same-origin',cache:'no-store'}),data=await response.json();if(effects.stopped||generation!==formGeneration)return;if(!response.ok)throw Error(data.error||'加载失败');byId('pestFormTitle').textContent=data.form_title||'植保作业工单';byId('woModalBody').innerHTML=data.form_html;const form=byId('pestWorkorderForm');window.IrrigationSubmissions?.begin('workorder',form);const selectionChanged=()=>{parameters?.sync();changed();};window.FOSWorkorderChips.mount(form,JSON.parse(form.querySelector('#pest-work-tree').textContent),JSON.parse(form.querySelector('#pest-preset-nodes').textContent),selectionChanged);picker=window.FOSLocationPicker.mount(form,JSON.parse(form.querySelector('#pest-location-options').textContent),ids.length?ids:JSON.parse(form.querySelector('#pest-preset-places').textContent),selectionChanged,enterMap);media=window.FOSWorkorderMedia.mount(form,changed);const parameterData=form.querySelector('#pest-parameter-schema');if(parameterData&&window.FOSWorkParameters)parameters=window.FOSWorkParameters.mount(form,JSON.parse(parameterData.textContent),changed);form.oninput=changed;form.onchange=changed;form.onsubmit=event=>{event.preventDefault();submit();};byId('woSubmitBtn').disabled=false;if(!ids.length&&!form.querySelector('[name=locations]'))picker.open();}
            catch(error){if(!effects.stopped&&generation===formGeneration)byId('woModalBody').textContent=error.message;}}
        async function submit() {
            const form=byId('pestWorkorderForm');
            if(busy || !form || !form.reportValidity()) return;
            const status=byId('pestSubmitStatus');
            if(!form.querySelector('[name=locations]')) {status.textContent='请选择作业地点。';picker.open();return;}
            if(!form.querySelector('[name=nodes]')) {status.textContent='请选择工作内容。';return;}
            const controls=[byId('woSubmitBtn'),byId('pestChangePlaces'),byId('pestCloseWorkorder')];
            const body=new FormData(form);
            busy=true;
            form.inert=true;
            form.setAttribute('aria-busy','true');
            controls.forEach(button=>button.disabled=true);
            status.textContent='正在提交…';
            let saved;
            try {
                const response=await fetch('/mobile/workorder/v2/', {
                    method:'POST',credentials:'same-origin',body,headers:{'X-Requested-With':'XMLHttpRequest'}
                });
                saved=await response.json();
                if(!response.ok || !saved.success) throw Error(saved.message || '提交失败');
            } catch(error) {
                if(!effects.stopped) status.textContent=error.message;
                return;
            } finally {
                busy=false;
                form.inert=false;
                form.removeAttribute('aria-busy');
                controls.forEach(button=>button.disabled=false);
            }
            if(!effects.stopped) {
                closeForm();
                notice(saved.number+' 已提交。');
                refresh();
            }
        }
        byId('pestCloseWorkorder').onclick=()=>closeForm();byId('woModalBackdrop').onclick=()=>closeForm();byId('woSubmitBtn').onclick=submit;byId('pestChangePlaces').onclick=()=>picker?.open();
        window.FOSPestMap={refresh,busy:()=>busy||creator.busy(),dirty:()=>dirty,openOverlays(){overlays?.openManager();},updateRole(data){closeForm();creator.close();canSubmit=data?.value==='yes';canManage=data?.manager==='yes';canCreate=data?.create==='yes';window.FOSMapActions.setItems(actions());},destroy(){effects.destroy();creator.destroy();picker?.destroy();media?.destroy();parameters?.destroy();overlays?.destroy();window.FOSMapActions.destroy();map.remove();}};
        window.quickWorkorder=ids=>openForm(ids);effects.listen(window,'focus',()=>{if(!busy&&!dirty)refresh();});effects.listen(window,'pageshow',event=>{if(event.persisted)refresh();});
        refresh();const incoming=new URL(location.href).searchParams;if(incoming.get('action')==='workorder'){const source={};for(const key of ['report_id','pest_task'])if(incoming.has(key))source[key]=incoming.get(key);openForm([],source);}
    });
})();
