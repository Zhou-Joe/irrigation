(function(){
    'use strict';
    const el=document.querySelector('[data-location-map]');if(!el)return;
    const status=document.getElementById('opMapStatus'),runtime=window.IrrigationMapRuntime,markers=window.FOSMapMarkers;
    const layout=document.querySelector('[data-location-layout]');
    const map=L.map(el,{preferCanvas:true}).setView([31.143,121.658],17),layers=L.layerGroup().addTo(map);
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{attribution:'Esri',maxZoom:22,maxNativeZoom:19}).addTo(map);
    markers.enableLabels(map);
    let initialized=false,places=[],generation=0,disposed=false,focusId=null,pendingFit=false;
    const shapes=new Map(),host=el.closest('.op-map-workspace');
    function notice(message,error=false){if(disposed)return;status.textContent=message;status.classList.toggle('op-error',error);}
    function mobileView(view,remember=true){
        if(!layout)return;layout.dataset.locationMobile=view;
        layout.querySelectorAll('[data-location-view]').forEach(button=>{const active=button.dataset.locationView===view;button.classList.toggle('is-active',active);button.setAttribute('aria-pressed',String(active));});
        if(remember)try{sessionStorage.setItem('fos-location-view',view);}catch(_){}
        requestAnimationFrame(()=>{if(!disposed){map.invalidateSize({pan:false});if(pendingFit)fit();}});
    }
    function focusRow(id){
        focusId=id;document.querySelectorAll('[data-location-row]').forEach(row=>row.classList.toggle('is-focused',row.dataset.locationRow===id));
        for(const [key,shape]of shapes)for(const item of shape.items){item.setStyle?.({weight:key===id?3:2,fillOpacity:key===id ? .24 : .14});item.getElement?.()?.classList.toggle('op-location-pin-selected',key===id);}
    }
    function fit(){
        if(!el.clientWidth||!el.clientHeight){pendingFit=true;return false;}
        pendingFit=false;
        const points=[...shapes.values()].flatMap(item=>item.points);
        if(points.length){map.invalidateSize({pan:false});map.fitBounds(L.latLngBounds(points).pad(.12),{maxZoom:19,animate:false});return true;}
        else notice('当前筛选条件下没有已定位地点。');
    }
    function render({fitView=false}={}){
        if(disposed)return;layers.clearLayers();shapes.clear();
        for(const place of places){
            if(el.dataset.location&&el.dataset.location!==place.id)continue;
            const popup=document.createElement('div'),link=document.createElement('a');link.href='/ops/locations/'+place.id+'/'+(new URL(location.href).searchParams.get('scope')==='catalog'?'?scope=catalog':'');link.textContent=place.name;popup.append(link);
            const description=document.createElement('p');description.textContent=[place.code,place.kind_label,place.source].filter(Boolean).join(' · ');popup.append(description);
            const rings=runtime.boundaryRings(place.boundary),shape=markers.presentation(place,rings),items=[],points=[];
            if(shape.mode==='boundary')for(const ring of rings){items.push(L.polygon(ring,{color:markers.descriptor(place.kind).color,weight:2,fillOpacity:.14}).bindPopup(popup.cloneNode(true)).addTo(layers));points.push(...ring);}
            else if(shape.mode==='pin'){items.push(markers.marker(L,place,shape.center).bindPopup(popup).addTo(layers));points.push(shape.center);}
            if(items.length)shapes.set(place.id,{items,points,center:shape.center});
            for(const layer of items)layer.on('click',event=>{if(creator.active()){L.DomEvent.stopPropagation(event);creator.pick(event.latlng||{lat:shape.center[0],lng:shape.center[1]});layer.closePopup();}else focusRow(place.id);});
        }
        if((!initialized||fitView)&&shapes.size)initialized=fit();
        if(focusId)focusRow(focusId);
        notice(shapes.size?'地图显示 '+shapes.size+' 个地点 · 点击列表中的定位图标可快速查看。':'当前没有已定位地点，可在地图上连续新建，或编辑地点后点选位置。');
    }
    async function load({fit:fitView=false}={}){
        if(disposed)return;const current=++generation;notice('正在加载地点…');
        try{
            const url=new URL(el.dataset.endpoint,location.href);
            for(const [key,value]of new URL(location.href).searchParams)if(key!=='scope'||!url.searchParams.has('scope'))url.searchParams.set(key,value);
            if(el.dataset.location)url.searchParams.set('location',el.dataset.location);
            const data=await runtime.fetchJSON(url.href,{cache:'no-store'});if(disposed||current!==generation)return;places=data.locations;render({fitView});
        }
        catch(_){if(!disposed&&current===generation){notice('地图数据暂不可用，请重试。',true);const retry=document.createElement('button');retry.type='button';retry.className='btn-sm btn-secondary';retry.textContent='重新加载';retry.onclick=()=>load();status.append(' ',retry);}}
    }
    async function focus(id){
        if(!places.length)await load();if(disposed)return;const shape=shapes.get(id);focusRow(id);
        if(!shape){notice('此地点尚未定位。点击“编辑”，即可在地图上设置位置。');return;}
        mobileView('map');requestAnimationFrame(()=>{if(disposed)return;map.invalidateSize({pan:false});map.fitBounds(L.latLngBounds(shape.points).pad(.2),{maxZoom:19,animate:!matchMedia('(prefers-reduced-motion: reduce)').matches});shape.items[0].openPopup();});
    }
    const creator=window.FOSMapLocationCreate.mount({map,panel:document.getElementById('mapLocationCreate'),markers,L,
        onOpen(){
            initialized=true;mobileView('map');host?.classList.add('is-creating');
            const url=new URL(location.href);for(const key of ['q','kind','ownership','positioned','page','source_team','visibility','scope'])url.searchParams.delete(key);history.replaceState(history.state,'',url);
            const search=document.querySelector('[data-location-search]');if(search)for(const field of search.elements){if(field.name==='q')field.value='';else if(field.name==='scope')field.value='team';else if(['kind','ownership','positioned','source_team','visibility'].includes(field.name))field.value='all';}
            Promise.all([load(),window.FOSBulkLocations?.refreshResults?.({maps:false})]).catch(()=>notice('列表暂未更新，地图仍可继续点选。'));
            el.scrollIntoView({block:'nearest',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
        },
        onClose(){host?.classList.remove('is-creating');requestAnimationFrame(()=>{if(!disposed)map.invalidateSize({pan:false});});},
        async onSaved(item){
            places=places.filter(place=>place.id!==item.id).concat({...item,kind_label:markers.descriptor(item.kind).label});render();
            try{await window.FOSBulkLocations?.refreshResults?.({maps:false});}catch(_){notice('地点已保存，列表暂未更新，请重新查询。');}
        }
    });
    map.on('click',event=>creator.pick(event.latlng));
    let dialog=null,editor=null,editorRequest=null,editorGeneration=0;
    function closeEditor(){editorGeneration++;editorRequest?.abort();editor?.destroy();editor=null;if(dialog?.open)dialog.close();}
    async function openEditor(url){
        if(dialog?.querySelector('form[data-busy]'))return;
        if(!dialog){
            dialog=document.createElement('dialog');dialog.className='ops-dialog loc-edit-dialog';dialog.setAttribute('aria-label','编辑地点');
            dialog.innerHTML='<header class="ops-dialog-head loc-dialog-head"><h2>编辑地点</h2><button type="button" class="ops-close" data-location-editor-close aria-label="关闭"><svg class="ui-icon"><use href="#pwa-close"/></svg></button></header><div class="ops-dialog-body loc-dialog-body"></div>';
            document.querySelector('.ops-page').append(dialog);
            dialog.addEventListener('cancel',event=>{if(dialog.querySelector('form[data-busy]'))event.preventDefault();else closeEditor();});
            dialog.addEventListener('close',()=>{editorGeneration++;editorRequest?.abort();editor?.destroy();editor=null;});
        }
        editorRequest?.abort();editor?.destroy();editor=null;
        const sequence=++editorGeneration,body=dialog.querySelector('.loc-dialog-body');body.textContent='正在加载地点资料…';if(!dialog.open)dialog.showModal();editorRequest=new AbortController();
        try{
            const response=await fetch(url,{credentials:'same-origin',cache:'no-store',signal:editorRequest.signal});
            if(!response.ok||response.redirected)throw Error('地点暂不可编辑，请确认账号权限。');
            const doc=new DOMParser().parseFromString(await response.text(),'text/html'),form=doc.querySelector('[data-location-edit]');
            if(!form)throw Error('表单暂不可用，请稍后重试。');if(sequence!==editorGeneration||!dialog.isConnected||!dialog.open)return;
            const imported=document.importNode(form,true);imported.setAttribute('action',url);body.replaceChildren(imported);editor=window.FOSLocationEditor.mount(imported);
        }catch(error){if(error.name!=='AbortError'&&sequence===editorGeneration)body.textContent=error.message||'加载失败，请关闭后重试。';}
    }
    async function saved(){
        if(!dialog?.open)return;closeEditor();const feedback=document.getElementById('opsFeedback');if(feedback){feedback.hidden=false;feedback.textContent='地点资料已保存。';feedback.classList.remove('error');}
        try{
            if(document.getElementById('opLocationResults'))await window.FOSBulkLocations.refreshResults();
            else{
                const response=await fetch(location.href,{credentials:'same-origin',cache:'no-store'});if(!response.ok)throw Error();
                const doc=new DOMParser().parseFromString(await response.text(),'text/html');
                for(const id of ['locationDetailTitle','locationDetailContent']){const old=document.getElementById(id),next=doc.getElementById(id);if(old&&next)old.replaceWith(next);}
                await load();
            }
        }catch(_){if(feedback)feedback.textContent='地点已保存，列表暂未更新，请重新查询。';}
    }
    function click(event){
        const create=event.target.closest('[data-map-create-open]');if(create){event.preventDefault();creator.open();return;}
        const view=event.target.closest('[data-location-view]');if(view){mobileView(view.dataset.locationView);return;}
        const target=event.target.closest('[data-location-focus]');if(target){event.preventDefault();focus(target.dataset.locationFocus);return;}
        if(event.target.closest('[data-location-fit]')){mobileView('map');requestAnimationFrame(fit);return;}
        const edit=event.target.closest('[data-location-edit-open]');if(edit){event.preventDefault();openEditor(edit.dataset.locationEditOpen||edit.getAttribute('href'));return;}
        if(event.target.closest('[data-location-editor-close]')){event.preventDefault();if(!dialog?.querySelector('form[data-busy]'))closeEditor();}
    }
    document.addEventListener('click',click);document.addEventListener('fos:location-saved',saved);
    const observer=typeof ResizeObserver==='function'?new ResizeObserver(()=>{if(!disposed)map.invalidateSize({pan:false});}):null;observer?.observe(el);
    function resume(event){if(event.persisted&&document.getElementById('opLocationResults'))window.FOSBulkLocations?.refreshResults().catch(()=>notice('地点列表暂未更新，请重新查询。'));}
    window.addEventListener('pageshow',resume);
    window.FOSLocationMap={refresh:load,focus,startCreation:()=>creator.open(),getView:()=>({center:map.getCenter(),zoom:map.getZoom()}),destroy(){disposed=true;generation++;closeEditor();dialog?.remove();observer?.disconnect();document.removeEventListener('click',click);document.removeEventListener('fos:location-saved',saved);window.removeEventListener('pageshow',resume);creator.destroy();map.remove();}};
    let preferred='list';try{preferred=sessionStorage.getItem('fos-location-view')||'list';}catch(_){}mobileView(preferred==='map'?'map':'list',false);load();
})();
