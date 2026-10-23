const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const runtime = require('../../static/js/map-runtime.js');
const ring = [[31,121],[31.01,121],[31,121.01]];

test('legacy, multi-ring and nested CAD formats retain every coordinate', () => {
    const objects = ring.map(([lat,lng]) => ({lat,lng}));
    for (const input of [ring, objects, [ring], [[objects]], [[],ring]]) {
        assert.deepEqual(runtime.boundaryRings(input), [ring]);
    }
    assert.deepEqual(runtime.boundaryRings([[ring],[objects]]), [ring,ring]);
});
test('bad points and empty groups cannot break another valid boundary', () => {
    assert.deepEqual(runtime.boundaryRings([[],[null,{lat:999,lng:121}],ring]), [ring]);
    for (const input of [null, {}, [], [[31,null],[false,121],['',121]]]) assert.deepEqual(runtime.boundaryRings(input), []);
    assert.equal(runtime.point([[31],[121]]), null);
    assert.deepEqual(runtime.point({lat:'31.123456789',lng:'121.123456789'}), [31.123456789,121.123456789]);
});
test('drawing labels receive finite object coordinates for imported multi-ring boundaries', () => {
    const input = [[], [ring, ring.map(([lat,lng])=>({lat,lng}))]];
    const before = JSON.stringify(input);
    const rings = runtime.boundaryObjects(input);
    assert.equal(rings.length,2);
    for (const points of rings) {
        const center = points.reduce((sum,p)=>({lat:sum.lat+p.lat,lng:sum.lng+p.lng}),{lat:0,lng:0});
        assert.ok(Number.isFinite(center.lat/points.length));
        assert.ok(Number.isFinite(center.lng/points.length));
        assert.deepEqual(points,ring.map(([lat,lng])=>({lat,lng})));
    }
    assert.equal(JSON.stringify(input),before);
});
test('patch filters agree for polygon and raw label records, including unassigned zones', () => {
    const chosen = new Set(['7']);
    assert.equal(runtime.matchesPatch({patchId:7},true,chosen),true);
    assert.equal(runtime.matchesPatch({patch_id:7},true,chosen),true);
    assert.equal(runtime.matchesPatch({patch_id:null},true,chosen),false);
    assert.equal(runtime.matchesPatch({},false,chosen),true);
});
test('rendering yields between batches and keeps order and exact totals', async () => {
    let frames=0, rendered=[], progress=[];
    await runtime.renderBatches(Array.from({length:101},(_,i)=>i), i=>rendered.push(i), {
        frame:cb=>{frames++;setImmediate(cb);}, now:()=>0, batchSize:40,
        progress:n=>progress.push(n)
    });
    assert.deepEqual(rendered, Array.from({length:101},(_,i)=>i));
    assert.equal(frames,3);
    assert.deepEqual(progress,[40,80,101]);
});
test('batch budget yields even before item limit; thrown failures reject', async () => {
    let clock=0,frames=0;
    await runtime.renderBatches([1,2,3],()=>{clock+=9;},{now:()=>clock,frame:cb=>{frames++;setImmediate(cb);}});
    assert.equal(frames,3);
    await assert.rejects(runtime.renderBatches([1],()=>{throw Error('bad render');},{frame:setImmediate}),/bad render/);
});
test('network errors and expired sessions reject; successful JSON keeps credentials', async () => {
    await assert.rejects(runtime.fetchJSON('/api/',{fetcher:async()=>({ok:false,status:503})}),/503/);
    await assert.rejects(runtime.fetchJSON('/api/',{fetcher:async()=>({ok:true,json:async()=>{throw Error('HTML login');}})}),/HTML login/);
    const data=await runtime.fetchJSON('/api/',{fetcher:async(url,opts)=>{
        assert.equal(opts.credentials,'same-origin');assert.ok(opts.signal);
        return {ok:true,json:async()=>[1]};
    }});
    assert.deepEqual(data,[1]);
});
test('stalled map requests abort instead of leaving the loading state forever', async () => {
    await assert.rejects(runtime.fetchJSON('/api/',{timeout:1,fetcher:(url,{signal})=>new Promise((resolve,reject)=>{
        signal.addEventListener('abort',()=>reject(Error('aborted')));
    })}),/aborted/);
});

test('location retries a slow GPS fix with the normal provider', async () => {
    const options=[];const fix={coords:{latitude:31,longitude:121,accuracy:50}};
    const actual=await runtime.requestLocation({getCurrentPosition(ok,fail,opts){
        options.push(opts);if(options.length===1)fail({code:3});else ok(fix);
    }});
    assert.equal(actual,fix);assert.equal(options[0].enableHighAccuracy,true);
    assert.equal(options[1].enableHighAccuracy,false);
});

test('denied location permissions are respected without repeated requests', async () => {
    let calls=0;
    await assert.rejects(runtime.requestLocation({getCurrentPosition(ok,fail){calls++;fail({code:1});}}),e=>e.code===1);
    assert.equal(calls,1);
});

test('unavailable or throwing location providers reject cleanly', async () => {
    let calls=0;
    await assert.rejects(runtime.requestLocation({getCurrentPosition(ok,fail){calls++;fail({code:2});}}),e=>e.code===2);
    assert.equal(calls,2);
    await assert.rejects(runtime.requestLocation({getCurrentPosition(){throw Error('blocked');}}),/blocked/);
});

// Execute the real map implementation with small Leaflet/DOM adapters. Tests
// expose private functions only in the VM; no debug API ships to production.
function mapHarness() {
    const span=()=>({style:{},textContent:''});
    const point=p=>Array.isArray(p)?{lat:p[0],lng:p[1]}:p;
    class Layer {
        constructor(points,opts={}) {this.points=points;this.options={...opts};this.el={style:{},querySelector:()=>this.span};this.span=span();}
        getElement(){return this.attached?this.el:null;}
        setLatLng(p){this.pos=point(p);return this;}
        getLatLng(){return this.pos||point(this.points);}
        setStyle(s){Object.assign(this.options,s);return this;}
        on(){return this;} bindTooltip(t){this.tooltip=t;return this;} bindPopup(){return this;}
        closeTooltip(){} bringToFront(){} addTo(group){group.addLayer(this);return this;}
        getBounds(){return {getCenter:()=>({lat:31,lng:121})};}
    }
    class Group {
        constructor(){this.layers=new Set();}
        addLayer(l){this.layers.add(l);l.attached=true;return this;}
        removeLayer(l){this.layers.delete(l);l.attached=false;return this;}
        hasLayer(l){return this.layers.has(l);} clearLayers(){for(const l of [...this.layers])this.removeLayer(l);}
        eachLayer(fn){[...this.layers].forEach(fn);} addTo(m){m.addLayer(this);return this;}
    }
    const groups=Array.from({length:6},()=>new Group());
    const map={zoom:15,west:120,east:122,layers:new Set(groups),getZoom(){return this.zoom;},getBounds(){return {
        pad(){return this;},contains:p=>p.lng>=map.west&&p.lng<=map.east,intersects:()=>true
    };},hasLayer(l){return this.layers.has(l);},addLayer(l){this.layers.add(l);},removeLayer(l){this.layers.delete(l);}};
    const elements={map:{dataset:{}},zoneLoadingMessage:{textContent:''},zoneLoadingSpinner:{},zoneLoadingRetry:{},
        'zone-loading-overlay':{style:{}},'zones-data':{textContent:''},'pipelines-data':{textContent:''},
        pipelineLoadNotice:{hidden:true},pipelineLoadingRetry:{}};
    const document={readyState:'loading',head:{appendChild(){}},createElement:()=>({}),
        addEventListener(){},dispatchEvent(){},getElementById:id=>elements[id]||null,querySelectorAll:()=>[],querySelector:()=>null};
    const window={IrrigationMapRuntime:{...runtime,
        renderBatches:(items,render,opts)=>runtime.renderBatches(items,render,{...opts,frame:setImmediate})}, __wmLayer:groups[5]};
    const L={tileLayer:()=>({}),layerGroup:()=>new Group(),divIcon:o=>o,latLng:(lat,lng)=>({lat,lng}),
        marker:(p,o)=>new Layer(p,o),polygon:(p,o)=>new Layer(p,o),polyline:(p,o)=>new Layer(p,o)};
    let source=fs.readFileSync(path.join(__dirname,'../../static/js/map.js'),'utf8');
    const hook=`window.__test={renderZones,loadZones,loadPipelines,locateUser,updateLabelSizes,_cullLabelsToViewport,buildCardHtml,_refreshZonePolygons,
        labels:()=>zoneLabels, setState(m,g){map=m;[zonesLayerGroup,labelsLayerGroup,leaderLinesLayerGroup,ringLabelsLayerGroup,landmarksLayerGroup]=g;}};`;
    source=source.replace(/\}\)\(\);\s*$/,hook+'})();');
    const context={window,document,L,localStorage:{getItem:()=>null,setItem(){}},console,setTimeout,clearTimeout,
        requestAnimationFrame:setImmediate,performance,Set,Map,CustomEvent:class{}};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../static/js/ui-icons.js'),'utf8'),context);
    vm.runInNewContext(source,context);
    window.__test.setState(map,groups);
    return {window,map,groups,api:window.__test,context,elements};
}
function zone(id,patch=1,lng=121) {
    return {id,code:`${id}-1-1`,name:'Map zone',land_name:'Land',patch_id:patch,
        boundary_points:ring.map(([lat,x])=>[lat,x+lng-121]),priority:'medium',plant_names:[]};
}
test('overview renders all boundaries while attaching zero hidden zone labels', async () => {
    const h=mapHarness();
    await h.api.renderZones(Array.from({length:2508},(_,i)=>zone(i+1)));
    assert.equal(h.groups[0].layers.size,2508);
    assert.equal(h.groups[1].layers.size,0);
    assert.equal(h.api.labels().length,2508);
    assert.equal(h.groups[5].layers.size,1);
});
test('zoom and pan attach only viewport labels; patch dimming survives reattachment', async () => {
    const h=mapHarness();await h.api.renderZones([zone(1,1,121),zone(2,2,125),zone(3,null,121)]);
    h.window.patchFilterTouched=true;h.window.activePatches=new Set(['1']);h.window.applyMapFilters();
    h.map.zoom=18;h.api.updateLabelSizes();assert.equal(h.groups[1].layers.size,2);
    assert.equal(h.api.labels()[2].getElement().style.opacity,'0.1');
    h.map.west=124;h.map.east=126;h.api._cullLabelsToViewport();assert.equal(h.groups[1].layers.size,1);
    assert.equal(h.api.labels()[1].getElement().style.opacity,'0.1');
});
test('label toggle hides watermarks and ring labels through subsequent zooms', async () => {
    const h=mapHarness();await h.api.renderZones([{...zone(1),boundary_points:[[ring],[ring]]}]);
    assert.equal(h.groups[0].layers.size,2);
    h.map.zoom=19;h.api.updateLabelSizes();assert.equal(h.groups[3].layers.size,2);
    h.window.setLayerVisibility('labels',false);assert.equal(h.groups[1].layers.size,0);
    assert.equal(h.groups[3].layers.size,0);assert.equal(h.groups[5].layers.size,0);
    h.map.zoom=20;h.api.updateLabelSizes();assert.equal(h.groups[1].layers.size,0);
});
test('popup titles and quick actions treat zone codes as text', () => {
    const h=mapHarness();const html=h.api.buildCardHtml({id:1,code:"A');alert(1);//",name:'<img src=x onerror=alert(1)>',pendingRequests:[]});
    assert.ok(!html.includes('<img src=x'));
    assert.ok(html.includes('&lt;img'));
    assert.ok(html.includes('window.quickWorkorder([this.dataset.zoneCode])'));
    assert.ok(!html.includes("quickWorkorder(['A"));
});
test('zone failure stays visible, offers retry, and a successful retry reaches ready', async () => {
    const h=mapHarness();h.context.console={...console,error(){}};
    h.window.IrrigationMapRuntime.fetchJSON=async()=>{throw Error('offline');};
    h.api.loadZones();await new Promise(setImmediate);await new Promise(setImmediate);
    assert.equal(h.elements.map.dataset.zonesState,'error');
    assert.equal(h.elements.zoneLoadingRetry.hidden,false);
    assert.notEqual(h.elements['zone-loading-overlay'].style.display,'none');
    h.window.IrrigationMapRuntime.fetchJSON=async()=>[zone(1)];
    h.elements.zoneLoadingRetry.onclick();await new Promise(setImmediate);await new Promise(setImmediate);
    assert.equal(h.elements.map.dataset.zonesState,'ready');
    assert.equal(h.elements['zone-loading-overlay'].style.display,'none');
});
test('pipeline failure is visible and does not clear successfully drawn zones', async () => {
    const h=mapHarness();await h.api.renderZones([zone(1)]);h.context.console={...console,error(){}};
    h.window.IrrigationMapRuntime.fetchJSON=async()=>{throw Error('offline');};
    h.api.loadPipelines();await new Promise(setImmediate);await new Promise(setImmediate);
    assert.equal(h.elements.pipelineLoadNotice.hidden,false);
    assert.equal(h.groups[0].layers.size,1);
    assert.equal(typeof h.elements.pipelineLoadingRetry.onclick,'function');
});
test('changing smoothing keeps popup metadata and never creates invisible overview labels', async () => {
    const h=mapHarness();const data={...zone(1),sprinkler_type:'Rotor',equipment_maintenance_notes:'[]',smooth_override:0};
    await h.api.renderZones([data]);h.window.zonesData=[data];
    h.api._refreshZonePolygons({id:1,smooth_override:2});
    assert.equal(h.groups[0].layers.size,1);
    const layer=[...h.groups[0].layers][0];
    assert.equal(layer.zoneData.sprinklerType,'Rotor');
    assert.equal(layer.zoneData.smooth_override,2);
    assert.equal(layer.points.length,12);
    assert.equal(h.groups[1].layers.size,0);
});
test('group work orders include every matching zone while map rendering is still in progress', async () => {
    const h=mapHarness();const first=zone(1), second=zone(2);
    h.window.zonesData=[first,second,{...zone(3),name:'Other'}];
    await h.api.renderZones([first]); // Only the first boundary has rendered so far.
    let chosen;h.window.quickWorkorder=codes=>{chosen=codes;};
    h.window._quickPatchWorkorder({getAttribute:name=>name==='data-zone-name'?'Map zone':first.code});
    assert.deepEqual([...chosen],[first.code,second.code]);
});

test('locate gives immediate feedback and explains a fix outside the project bounds', async () => {
    const h=mapHarness();let done,flights=0;
    h.context.navigator={geolocation:{getCurrentPosition(ok){done=ok;}}};
    const button={disabled:false,setAttribute(n,v){this[n]=v;},removeAttribute(n){delete this[n];}};
    h.context.document.querySelector=()=>button;
    for(const name of ['mapLocationNotice','mapLocationMessage','mapLocationRetry','mapLocationClose'])h.elements[name]={hidden:true};
    h.map.options={maxBounds:{contains:()=>false}};h.map.flyTo=()=>flights++;
    h.context.L.circle=()=>({addTo(){return this;}});
    const pending=h.api.locateUser();
    assert.equal(button.disabled,true);assert.equal(button['aria-busy'],'true');
    assert.match(h.elements.mapLocationMessage.textContent,/正在定位/);
    done({coords:{latitude:31,longitude:121,accuracy:8}});await pending;
    assert.equal(flights,0);assert.match(h.elements.mapLocationMessage.textContent,/项目范围外/);
    assert.match(h.elements.mapLocationMessage.textContent,/8 米/);
    assert.equal(button.disabled,false);assert.equal(button['aria-busy'],undefined);
});

test('locate failure restores the button and offers retry with a useful permission message', async () => {
    const h=mapHarness();h.context.navigator={geolocation:{getCurrentPosition(ok,fail){fail({code:1});}}};
    const button={disabled:false,setAttribute(){},removeAttribute(){}};h.context.document.querySelector=()=>button;
    for(const name of ['mapLocationNotice','mapLocationMessage','mapLocationRetry','mapLocationClose'])h.elements[name]={hidden:true};
    await h.api.locateUser();
    assert.equal(button.disabled,false);assert.equal(h.elements.mapLocationRetry.hidden,false);
    assert.match(h.elements.mapLocationMessage.textContent,/定位权限未开启/);
    assert.equal(typeof h.elements.mapLocationRetry.onclick,'function');
});
