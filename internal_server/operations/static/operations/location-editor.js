(function () {
    'use strict';
    const el = document.getElementById('opPointMap');
    if (!el) return;
    const markers = window.FOSMapMarkers;
    const map = L.map(el).setView([31.143,121.658],17);
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{
        maxZoom:22,maxNativeZoom:19,attribution:'Esri'
    }).addTo(map);
    markers.enableLabels(map);
    const lat = document.getElementById('id_latitude'), lng = document.getElementById('id_longitude');
    const kind = document.getElementById('id_kind'), name = document.getElementById('id_name');
    let pin;
    function update() {
        if (pin) {map.removeLayer(pin); pin = null;}
        const shape = markers.presentation({latitude:lat.value,longitude:lng.value},[]);
        if (shape.mode === 'pin') pin = markers.marker(L,{kind:kind.value,name:name.value},shape.center).addTo(map);
    }
    update();
    if (pin) map.setView(pin.getLatLng(),18);
    map.on('click',function (event) {
        lat.value = event.latlng.lat.toFixed(7); lng.value = event.latlng.lng.toFixed(7);
        update(); window.opsDirty = true;
    });
    for (const input of [lat,lng,kind,name]) input.addEventListener('input',update);
})();
