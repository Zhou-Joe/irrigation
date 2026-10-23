/* Text is measured once into a small high-DPI tile, never an animated canvas.
   Enterprise watermark reference: https://ant.design/components/watermark/ */
(function () {
    'use strict';
    function wrapText(text,maxWidth,measure) {
        const lines=[];let line='';
        for (const character of Array.from(String(text))) {
            if (line && measure(line+character)>maxWidth) { lines.push(line);line=''; }
            line+=character;
        }
        if (line) lines.push(line);
        return lines;
    }
    function layout(identity,warning,measure,mobile) {
        const size=mobile ? 11 : 12,maxWidth=mobile ? 190 : 260;
        const rows=[];
        [[identity,size],[warning,size-1]].forEach(([text,fontSize]) => {
            wrapText(text,maxWidth,value=>measure(value,fontSize)).forEach(value=>rows.push({text:value,size:fontSize}));
        });
        const width=Math.max(0,...rows.map(row=>measure(row.text,row.size)));
        const height=rows.reduce((sum,row)=>sum+row.size+6,0);
        const angle=-22*Math.PI/180;
        const rotatedWidth=Math.abs(width*Math.cos(angle))+Math.abs(height*Math.sin(angle));
        const rotatedHeight=Math.abs(width*Math.sin(angle))+Math.abs(height*Math.cos(angle));
        return {rows,height,angle,rotatedWidth,rotatedHeight,
            width:Math.ceil(Math.max(mobile ? 300 : 380,rotatedWidth+64)),
            tileHeight:Math.ceil(Math.max(mobile ? 210 : 240,rotatedHeight+80))};
    }
    function pixelRatio(value) { return Math.max(1,Math.min(3,Number(value)||1)); }
    if (typeof module==='object' && module.exports) { module.exports={wrapText,layout,pixelRatio};return; }
    const root=document.querySelector('[data-site-watermark]');
    if (!root) return;
    const identity=root.dataset.identity,warning=root.dataset.warning;
    const ns='http://www.w3.org/2000/svg',layers=new Map([[document.body,root]]);
    let currentTile=null,sequence=0,signature='',frame=0;
    function svgElement(tag,attributes) {
        const node=document.createElementNS(ns,tag);
        Object.entries(attributes).forEach(([name,value])=>node.setAttribute(name,String(value)));
        return node;
    }
    function paintLayer(layer) {
        if (!currentTile) return;
        const id='site-watermark-pattern-'+(++sequence);
        const svg=svgElement('svg',{class:'watermark-canvas',width:'100%',height:'100%',focusable:'false'});
        const defs=svgElement('defs',{});
        const pattern=svgElement('pattern',{id,width:currentTile.width,height:currentTile.height,patternUnits:'userSpaceOnUse'});
        pattern.append(svgElement('image',{href:currentTile.url,width:currentTile.width,height:currentTile.height}));
        defs.append(pattern);svg.append(defs,svgElement('rect',{width:'100%',height:'100%',fill:'url(#'+id+')'}));
        layer.replaceChildren(svg);
    }
    function addLayer(host) {
        if (layers.has(host)) return;
        const layer=document.createElement('div');layer.className='anti-leak-watermark';
        layer.setAttribute('aria-hidden','true');layer.setAttribute('inert','');
        host.append(layer);layers.set(host,layer);
        if (currentTile) paintLayer(layer);
        else if (root.firstElementChild) {
            const fallback=root.firstElementChild.cloneNode(true);
            const pattern=fallback.querySelector('pattern'),rect=fallback.querySelector('rect');
            const id='site-watermark-fallback-'+(++sequence);
            if (pattern && rect) { pattern.id=id;rect.setAttribute('fill','url(#'+id+')'); }
            layer.append(fallback);
        }
    }
    function render() {
        frame=0;
        const mobile=window.innerWidth<=768,ratio=pixelRatio(window.devicePixelRatio);
        const nextSignature=mobile+':'+ratio;
        if (signature===nextSignature) return;
        try {
            const canvas=document.createElement('canvas'),context=canvas.getContext('2d');
            if (!context) return; // The server SVG stays visible when canvas is unavailable.
            const family=getComputedStyle(document.body).fontFamily || 'sans-serif';
            const measure=(text,size)=>{context.font='400 '+size+'px '+family;return context.measureText(text).width;};
            const geometry=layout(identity,warning,measure,mobile);
            canvas.width=Math.ceil(geometry.width*ratio);canvas.height=Math.ceil(geometry.tileHeight*ratio);
            context.scale(ratio,ratio);context.translate(geometry.width/2,geometry.tileHeight/2);context.rotate(geometry.angle);
            context.textAlign='center';context.textBaseline='middle';context.lineJoin='round';context.lineWidth=.7;
            let y=-geometry.height/2;
            geometry.rows.forEach(row=>{
                context.font='400 '+row.size+'px '+family;
                context.strokeStyle='rgba(255,255,255,.28)';context.fillStyle='rgba(35,55,43,.13)';
                context.strokeText(row.text,0,y+(row.size+6)/2);context.fillText(row.text,0,y+(row.size+6)/2);
                y+=row.size+6;
            });
            currentTile={url:canvas.toDataURL('image/png'),width:geometry.width,height:geometry.tileHeight};
            signature=nextSignature;
            layers.forEach((layer,host)=>{
                if (host!==document.body && !host.isConnected) { layers.delete(host);return; }
                paintLayer(layer);
            });
        } catch (_) { /* Keep the vector fallback; never break the page or its forms. */ }
    }
    function schedule() { if (!frame) frame=requestAnimationFrame(render); }
    render();
    window.addEventListener('resize',schedule,{passive:true});
    // Native dialogs/fullscreen live above ordinary z-index stacking contexts.
    document.querySelectorAll('dialog').forEach(dialog=>{
        const sync=()=>{if(dialog.open)addLayer(dialog);};
        new MutationObserver(sync).observe(dialog,{attributes:true,attributeFilter:['open']});sync();
    });
    document.addEventListener('fullscreenchange',()=>{
        const host=document.fullscreenElement;
        if(host && host!==document.documentElement && host!==document.body)addLayer(host);
    });
    // Shallow observation avoids watching thousands of Leaflet map mutations.
    // This repairs accidental removal/basic style changes, not a security boundary.
    const restore=()=>{
        if (!root.isConnected) document.body.append(root);
        if (root.className!=='anti-leak-watermark') root.className='anti-leak-watermark';
        if (root.hasAttribute('style')) root.removeAttribute('style');
        if (root.hidden) root.hidden=false;
    };
    new MutationObserver(restore).observe(document.body,{childList:true});
    new MutationObserver(restore).observe(root,{attributes:true,attributeFilter:['style','class','hidden']});
})();
