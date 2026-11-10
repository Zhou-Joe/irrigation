(function(){
    'use strict';
    const el=document.querySelector('[data-location-map]');if(!el)return;
    const status=document.getElementById('opMapStatus'),runtime=window.IrrigationMapRuntime,markers=window.FOSMapMarkers;
    const map=L.map(el).setView([31.143,121.658],17),layers=L.layerGroup().addTo(map);
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{attribution:'Esri',maxZoom:22,maxNativeZoom:19}).addTo(map);
    markers.enableLabels(map);let initialized=false,places=[],generation=0;
    function render(){
        layers.clearLayers();const points=[];let count=0;
        for(const place of places){
            if(el.dataset.location&&el.dataset.location!==place.id)continue;
            const popup=document.createElement('a');popup.href='/ops/locations/'+place.id+'/';popup.textContent=place.name+(place.code?' · '+place.code:'');
            const rings=runtime.boundaryRings(place.boundary),shape=markers.presentation(place,rings),items=[];
            if(shape.mode==='boundary'){for(const ring of rings){items.push(L.polygon(ring,{color:markers.descriptor(place.kind).color,weight:2,fillOpacity:.14}).bindPopup(popup.cloneNode(true)).addTo(layers));points.push(...ring);}count++;}
            else if(shape.mode==='pin'){items.push(markers.marker(L,place,shape.center).bindPopup(popup).addTo(layers));points.push(shape.center);count++;}
            for(const layer of items)layer.on('click',event=>{if(creator.active()){L.DomEvent.stopPropagation(event);creator.pick(event.latlng||{lat:shape.center[0],lng:shape.center[1]});layer.closePopup();}});
        }
        if(!initialized&&points.length){map.fitBounds(L.latLngBounds(points).pad(.15),{maxZoom:19});initialized=true;}
        status.textContent=count?'已显示 '+count+' 个地点。':'尚无已定位地点，可在地图上新增。';
    }
    async function load(){
        const current=++generation;status.textContent='正在加载地点…';
        try{const data=await runtime.fetchJSON(el.dataset.endpoint+location.search,{cache:'no-store'});if(current!==generation)return;places=data.locations;render();}
        catch(_){if(current===generation){status.textContent='地图数据暂不可用。';const retry=document.createElement('button');retry.type='button';retry.className='op-btn op-secondary';retry.textContent='重试';retry.onclick=load;status.append(' ',retry);}}
    }
    const host=el.closest('.op-map-workspace');
    function resize(){const center=map.getCenter(),zoom=map.getZoom();requestAnimationFrame(()=>{map.invalidateSize({pan:false});map.setView(center,zoom,{animate:false});});}
    const creator=window.FOSMapLocationCreate.mount({map,panel:document.getElementById('mapLocationCreate'),markers,L,
        onOpen(){initialized=true;host?.classList.add('is-creating');resize();const url=new URL(location.href);url.searchParams.delete('q');url.searchParams.delete('page');history.replaceState(history.state,'',url);const search=document.querySelector('[data-location-search] input[name=q]');if(search)search.value='';el.scrollIntoView({block:'start',behavior:'smooth'});},
        onClose(){host?.classList.remove('is-creating');resize();},
        async onSaved(item){places=places.filter(p=>p.id!==item.id).concat({...item,kind_label:markers.descriptor(item.kind).label,map_display:'pin',boundary:[],center:[Number(item.latitude),Number(item.longitude)]});render();await window.FOSBulkLocations?.refreshResults?.({maps:false});}
    });
    map.on('click',event=>creator.pick(event.latlng));
    document.querySelector('[data-map-create-open]')?.addEventListener('click',()=>creator.open());
    window.FOSLocationMap={refresh:load,startCreation:()=>creator.open(),destroy(){generation++;creator.destroy();map.remove();}};load();
})();
