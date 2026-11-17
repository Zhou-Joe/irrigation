/* Read-only shared locations on the existing irrigation map. Never moves the viewport. */
(function(){
    'use strict';
    window.FOSSharedLocationLayer={mount({map,checkbox,status,retry}){
        if(!map||!checkbox)return null;
        const effects=window.FOSScopedEffects(),group=L.layerGroup(),markers=window.FOSMapMarkers;
        let generation=0;
        markers.enableLabels(map);
        function popup(place){
            const box=document.createElement('div'),title=document.createElement('strong'),text=document.createElement('p');
            title.textContent=place.name;text.textContent=[place.kind_label,place.owner_team,'共享地点 · 只读'].filter(Boolean).join(' · ');box.append(title,text);return box;
        }
        async function refresh(){
            if(effects.stopped||!checkbox.checked)return;
            const current=++generation;status.textContent='正在加载共享地点…';retry.hidden=true;
            try{
                const data=await window.IrrigationMapRuntime.fetchJSON('/ops/locations.geojson?shared=1',{cache:'no-store'});
                if(effects.stopped||current!==generation||!checkbox.checked)return;
                group.clearLayers();let count=0;
                for(const place of data.locations){
                    const rings=window.IrrigationMapRuntime.boundaryRings(place.boundary),shape=markers.presentation(place,rings),body=popup(place);
                    if(shape.mode==='boundary'){
                        for(const ring of rings)L.polygon(ring,{color:markers.descriptor(place.kind).color,weight:2,fillOpacity:.14,dashArray:'6 4'}).bindPopup(body.cloneNode(true)).addTo(group);
                        count++;
                    }else if(shape.mode==='pin'){markers.marker(L,place,shape.center).bindPopup(body).addTo(group);count++;}
                }
                status.textContent=count?'已显示 '+count+' 个共享地点':'暂无已定位的共享地点';
            }catch(error){if(!effects.stopped&&current===generation){group.clearLayers();status.textContent='共享地点加载失败';retry.hidden=false;}}
        }
        function toggle(){
            generation++;
            if(checkbox.checked){if(!map.hasLayer(group))map.addLayer(group);refresh();}
            else{group.clearLayers();if(map.hasLayer(group))map.removeLayer(group);status.textContent='共享地点已隐藏';retry.hidden=true;}
        }
        effects.listen(checkbox,'change',toggle);effects.listen(retry,'click',refresh);effects.listen(window,'focus',refresh);
        effects.listen(window,'pageshow',event=>{if(event.persisted)refresh();});
        effects.interval(()=>{if(document.visibilityState!=='hidden')refresh();},30000);
        toggle();
        return {refresh,destroy(){generation++;effects.destroy();group.clearLayers();if(map.hasLayer(group))map.removeLayer(group);}};
    }};
})();
