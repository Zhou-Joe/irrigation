(() => {
    'use strict';
    const el = id => document.getElementById(id), icons = window.IrrigationValveIcons;
    const controls = el('pipeControls'), list = el('pipeObject'), target = el('targetPipe');
    const save = el('saveGeo'), reset = el('resetGeo'), status = el('editStatus');
    const map = L.map('pipeCanvas', {preferCanvas:true,maxZoom:22}).setView([31.145663,121.655407],16);
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxNativeZoom:19,maxZoom:22,attribution:'Esri'}).addTo(map);
    const base = L.layerGroup().addTo(map), edits = L.layerGroup().addTo(map);
    const valves = L.layerGroup(), valveEdits = L.layerGroup();
    function updateValveVisibility() {
        icons.syncLayer(map, valves);
        icons.syncLayer(map, valveEdits);
    }
    map.on('zoomend', updateValveVisibility);
    updateValveVisibility();
    const items = new Map(), pipes = new Map();
    let selected = null, draft = [], dirty = false, busy = false;
    const pt = ll => ({lat: Number(ll.lat.toFixed(7)),lng:Number(ll.lng.toFixed(7))});
    const coords = v => {const ll=L.latLng(v); return {lat:ll.lat,lng:ll.lng};};
    function changed(value) {
        dirty = value;
        save.disabled = !dirty;
        reset.disabled = !dirty;
        if (dirty) status.textContent = '修改待保存。';
    }
    function fillList() {
        const term = el('pipeSearch').value.trim().toLowerCase();
        const options = [new Option('选择管线或设备','')];
        for (const [key,item] of items) if (key===selected?.key || item.label.toLowerCase().includes(term)) options.push(new Option(item.label,key));
        list.replaceChildren(...options); list.value = selected?.key || '';
    }
    function targetPipe(id) {
        if (selected?.kind !== 'pending') return;
        target.value = String(id || '');
        el('valveKind').disabled = el('targetZone').disabled = !target.value;
        save.textContent = target.value ? '保存并挂接' : '保存位置';
        changed(true);
        pipes.forEach((p,k)=>p.layer.setStyle({weight:String(k)===target.value?7:3}));
    }
    function show(item, zoom=true) {
        if (busy || dirty && !confirm('放弃尚未保存的修改？')) { list.value=selected?.key || ''; return; }
        if (selected?.layer) selected.parent.addLayer(selected.layer);
        pipes.forEach(p=>p.layer.setStyle({weight:3}));
        selected = item; edits.clearLayers(); valveEdits.clearLayers(); changed(false); fillList();
        el('pendingFields').hidden = item?.kind !== 'pending';
        target.value=''; el('targetZone').value=''; el('valveKind').value=item?.type || '';
        el('targetZone').disabled=el('valveKind').disabled=true; save.textContent='保存修改';
        if (!item) return;
        draft = item.points.map(coords);
        if (zoom) map.fitBounds(L.latLngBounds(draft),{maxZoom:20,padding:[30,30],animate:false});
        item.parent.removeLayer(item.layer);
        if (item.kind==='pipe') {
            const line=L.polyline(draft,{weight:5,color:'#15815e'}).addTo(edits);
            draft.forEach((v,i)=>{
                const vertex=L.marker(v,{draggable:true,icon:L.divIcon({className:'vertex-handle',iconSize:[12,12]}),title:'顶点 '+(i+1)}).addTo(edits);
                vertex.on('drag',()=>{draft[i]=pt(vertex.getLatLng());line.setLatLngs(draft);changed(true);});
            });
            el('editHint').textContent='拖动白色顶点可局部修改管线。';
        } else {
            const handle=L.marker(draft[0],{...icons.options(item.type,{pending:item.kind==='pending',size:25}),draggable:true,zIndexOffset:1200}).addTo(valveEdits);
            handle.on('dragend',()=>{draft[0]=pt(handle.getLatLng());changed(true);});
            el('editHint').textContent=item.kind==='pending'?'拖动设备调整位置。点选地图上的目标管线或用下拉框选择，再保存挂接。':'拖动选中的阀门调整位置。重叠设备可从列表分别选择。';
        }
        status.textContent=item.label;
    }
    function add(item, layer) {
        item.layer=layer; item.parent = item.kind === 'pipe' ? base : valves; items.set(item.key,item);
        layer.bindTooltip(document.createTextNode(item.label));
        layer.on('click',()=>{
            if (busy) return;
            if (selected?.kind==='pending' && item.kind==='pipe') targetPipe(item.id);
            else show(item);
        }).addTo(item.parent);
    }
    async function load(focusKey) {
        const response=await fetch('/pipelines/edit/data/?editor=1',{cache:'no-store'});
        if (!response.ok) throw Error('管网加载失败，请刷新重试。');
        const data=await response.json();
        edits.clearLayers();valveEdits.clearLayers();base.clearLayers();valves.clearLayers();items.clear();pipes.clear();selected=null;changed(false);
        const targets=[new Option('仅调整设备位置','')];
        for (const p of data.pipelines) {
            if (!p.line_points?.length) continue;
            const item={kind:'pipe',key:'p'+p.id,id:p.id,label:'管线 · '+p.code+' '+p.name,points:p.line_points};
            add(item,L.polyline(item.points,{weight:3,color:p.color||'#a84a38'}));pipes.set(p.id,item);
            targets.push(new Option(item.label,String(p.id)));
        }
        target.replaceChildren(...targets);
        el('targetZone').replaceChildren(new Option('未指定',''),...data.zones.map(z=>new Option(z.label,String(z.id))));
        for (const v of data.valves) {
            if (!v.point?.length) continue;
            const label=icons.label(v.type)+' #'+v.id+' · '+(v.name || '未命名设备')+' · '+(pipes.get(v.pipeline_id)?.label || '');
            add({key:'v'+v.id,kind:'valve',id:v.id,type:v.type,label,points:v.point},L.marker(v.point[0],icons.options(v.type)));
        }
        for (const v of data.pending) {
            if (!v.source_id) continue;
            const pos={lat:v.lat,lng:v.lng}, label='待挂接 · '+icons.label(v.type)+' · '+v.block+' · '+v.batch+' / '+v.source_id;
            add({key:'u'+v.batch_id+':'+v.source_id,kind:'pending',batch:v.batch_id,sid:v.source_id,type:v.type,label,points:[pos]},L.marker(pos,icons.options(v.type,{pending:true})));
        }
        controls.disabled=false; busy=false;fillList();
        if (focusKey && items.has(focusKey)) show(items.get(focusKey));
        else {show(null);status.textContent='已加载 '+data.pipelines.length+' 条管线，'+data.valves.length+' 个已挂接设备，'+data.pending.length+' 个待挂接设备。';}
    }
    el('pipeSearch').oninput=fillList;
    list.onchange=()=>show(items.get(list.value) || null);
    target.onchange=()=>targetPipe(target.value);
    reset.onclick=()=>{changed(false);show(selected,false);};
    save.onclick=async()=>{
        if (!selected || !dirty || busy) return;
        busy=true;controls.disabled=true;status.textContent='正在保存…';
        const item=selected, fd=new FormData();
        let url, key=item.key;
        if (item.kind==='pipe') {
            url='/pipelines/edit/pipeline/'+item.id+'/geometry/';fd.set('original',JSON.stringify(item.points));fd.set('line_points',JSON.stringify(draft));
        } else if (item.kind==='valve') {
            url='/pipelines/edit/valve/'+item.id+'/update/';fd.set('original',JSON.stringify(item.points));fd.set('point',JSON.stringify(draft[0]));
        } else {
            url='/pipelines/edit/pending/'+item.batch+'/';fd.set('original',JSON.stringify(item.points[0]));fd.set('source_id',item.sid);
            fd.set('lat',draft[0].lat);fd.set('lng',draft[0].lng);fd.set('pipeline',target.value);fd.set('type',el('valveKind').value);fd.set('zone',el('targetZone').value);
        }
        try {
            const r=await fetch(url,{method:'POST',body:fd,headers:{'X-CSRFToken':controls.querySelector('[name=csrfmiddlewaretoken]').value}});
            const data=await r.json();
            if (!r.ok || !data.success) throw Error(data.error || '保存失败。');
            if (data.valve_id) key='v'+data.valve_id;
            changed(false);await load(key);status.textContent='已保存。';
        } catch(e){status.textContent=e.message;} finally{busy=false;controls.disabled=false;}
    };
    window.addEventListener('beforeunload',e=>{if (dirty){e.preventDefault();e.returnValue='';}});
    const q=new URLSearchParams(location.search);
    load(q.has('source')?'u'+q.get('batch')+':'+q.get('source'):null).catch(e=>status.textContent=e.message);
})();
