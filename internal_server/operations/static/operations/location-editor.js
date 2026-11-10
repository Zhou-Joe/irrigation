/* The same point editor mounts on a full form or an in-place location dialog. */
(function () {
    'use strict';
    const mounted=new WeakMap(),active=new Set();
    function mount(form){
        if(mounted.has(form))return mounted.get(form);
        const el=form.querySelector('#opPointMap'),lat=form.elements.latitude,lng=form.elements.longitude;
        if(!el||!lat||!lng)return {destroy(){}};
        const markers=window.FOSMapMarkers,kind=form.elements.kind,name=form.elements.name;
        const initial=window.FOSLocationMap?.getView?.();
        const map=L.map(el).setView(initial?.center||[31.143,121.658],initial?.zoom||17);
        L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{
            maxZoom:22,maxNativeZoom:19,attribution:'Esri'
        }).addTo(map);
        markers.enableLabels(map);let pin=null,disposed=false;
        function update(){
            if(disposed)return;if(pin){map.removeLayer(pin);pin=null;}
            const shape=markers.presentation({latitude:lat.value,longitude:lng.value},[]);
            if(shape.mode==='pin')pin=markers.marker(L,{kind:kind.value,name:name.value},shape.center).addTo(map);
        }
        update();if(pin)map.setView(pin.getLatLng(),18);
        map.on('click',event=>{
            lat.value=event.latlng.lat.toFixed(7);lng.value=event.latlng.lng.toFixed(7);update();
            lat.dispatchEvent(new Event('input',{bubbles:true}));window.opsDirty=true;
        });
        const inputs=[lat,lng,kind,name];inputs.forEach(input=>input.addEventListener('input',update));
        // Optional coordinate fields stay collapsed while the map remains usable.
        const observer=typeof ResizeObserver==='function'?new ResizeObserver(()=>{if(!disposed)map.invalidateSize({pan:false});}):null;
        observer?.observe(el);
        const controller={destroy(){if(disposed)return;disposed=true;observer?.disconnect();inputs.forEach(input=>input.removeEventListener('input',update));map.remove();active.delete(controller);mounted.delete(form);}};
        active.add(controller);mounted.set(form,controller);
        requestAnimationFrame(()=>{if(!disposed)map.invalidateSize({pan:false});});return controller;
    }
    window.FOSLocationEditor={mount,destroyAll(){for(const controller of [...active])controller.destroy();}};
    document.querySelectorAll('[data-location-edit]').forEach(mount);
})();
