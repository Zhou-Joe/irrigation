(() => {
    'use strict';
    const el = id => document.getElementById(id);
    const pad = el('shapePad'), ink = el('shapeInk'), kind = el('shapeKind'), offset = el('shapeOffset');
    const save = el('shapeSave'), undo = el('shapeUndo'), reset = el('shapeDefault'), status = el('shapeStatus');
    const library = JSON.parse(el('shape-library').textContent), icons = window.IrrigationValveIcons;
    const tools = [...document.querySelectorAll('[data-tool]')];
    let type = kind.value, tool = 'pen', paths = [], current = null, start = null;
    let cursor = [32,32], pointer = null, keyboard = false, saving = false;
    const clamp = v => Math.max(0,Math.min(64,Math.round(v)));
    const saved = () => library[type] || {paths:[],offset:0,revision:0};
    const dirty = () => JSON.stringify(paths) !== JSON.stringify(saved().paths) || Number(offset.value) !== saved().offset;
    function refresh() {
        ink.replaceChildren();
        for (const points of current ? [...paths,current] : paths) {
            const line = document.createElementNS(pad.namespaceURI,'polyline');
            line.setAttribute('points', points.map(p=>p.join(',')).join(' '));
            ink.append(line);
        }
        const shape = {paths,offset:Number(offset.value)};
        el('shapePreviewZero').innerHTML = icons.markup(type,{shape});
        el('shapePreviewTurn').innerHTML = icons.markup(type,{shape,orientation:{angle:60}});
        offset.disabled = saving || !paths.length;
        save.disabled = saving || !!current || !dirty() || !offset.validity.valid;
        undo.disabled = saving || !paths.length;
        reset.disabled = saving || !paths.length;
        kind.disabled = saving;
        for (const button of tools) button.disabled = saving;
    }
    function load() {
        current = null; start = null; keyboard = false; pointer = null;
        paths = saved().paths.slice(); offset.value = saved().offset;
        status.textContent = paths.length ? '已载入自定义图案。' : '当前使用默认图标。';
        refresh();
    }
    function locate(event) {
        const point = pad.createSVGPoint(); point.x = event.clientX; point.y = event.clientY;
        const local = point.matrixTransform(pad.getScreenCTM().inverse());
        return [clamp(local.x),clamp(local.y)];
    }
    function begin(point) {
        if (paths.length >= 32) {status.textContent='每个图案最多 32 笔，请先撤销一笔。';return false;}
        start = point; current = [point]; return true;
    }
    function extend(point) {
        if (tool === 'pen') {
            if (current.length < 256 && current.at(-1).some((v,i)=>v!==point[i])) current.push(point);
        } else if (tool === 'line') current = [start,point];
        else {
            const [x,y] = start, radius = Math.min(Math.hypot(point[0]-x,point[1]-y),x,y,64-x,64-y);
            current = Array.from({length:33},(_,i) => [clamp(x+radius*Math.cos(i*Math.PI/16)),clamp(y+radius*Math.sin(i*Math.PI/16))]);
        }
        refresh();
    }
    function finish() {
        if (current?.some(p=>p[0]!==current[0][0] || p[1]!==current[0][1])) {
            paths.push(current); status.textContent='图案已修改，等待保存。';
        }
        current = null; start = null; keyboard = false; pointer = null; refresh();
    }
    pad.addEventListener('pointerdown', event => {
        if (saving || !event.isPrimary || event.button !== 0 || current) return;
        if (!begin(locate(event))) return;
        event.preventDefault(); pointer = event.pointerId; pad.setPointerCapture(pointer); refresh();
    });
    pad.addEventListener('pointermove', event => { if (pointer===event.pointerId) extend(locate(event)); });
    pad.addEventListener('pointerup', event => { if (pointer===event.pointerId) { extend(locate(event)); finish(); } });
    function cancelStroke() { current = null; start = null; pointer = null; keyboard = false; refresh(); }
    pad.addEventListener('pointercancel', cancelStroke);
    pad.addEventListener('lostpointercapture',event=>{if(pointer===event.pointerId)cancelStroke();});
    pad.addEventListener('keydown',event=>{
        if (saving || pointer!==null) return;
        const steps={ArrowRight:[1,0],ArrowLeft:[-1,0],ArrowDown:[0,1],ArrowUp:[0,-1]};
        if (steps[event.key]) {
            event.preventDefault();
            cursor=cursor.map((n,i)=>clamp(n+steps[event.key][i]*(event.shiftKey?1:4)));
            el('shapeCursor').setAttribute('cx',cursor[0]); el('shapeCursor').setAttribute('cy',cursor[1]);
            if(keyboard)extend(cursor);
        } else if (event.key===' ' || event.key==='Enter') {
            event.preventDefault(); if (event.repeat) return;
            if(keyboard)finish(); else if(begin(cursor)) {keyboard=true;refresh();}
        } else if(event.key==='Escape')cancelStroke();
    });
    for (const button of tools) button.onclick=()=>{
        cancelStroke();tool=button.dataset.tool;
        tools.forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
        el('shapeInstructions').textContent=({pen:'拖动绘制一笔。',line:'从起点拖到终点绘制直线。',circle:'从圆心向外拖动绘制圆形。'})[tool]+'也可以用方向键移动光标，按空格开始或结束。';
    };
    undo.onclick=()=>{cancelStroke();paths.pop();if(!paths.length)offset.value=0;status.textContent='已撤销最后一笔。';refresh();};
    reset.onclick=()=>{cancelStroke();paths=[];offset.value=0;status.textContent='保存后恢复默认图标。';refresh();};
    offset.oninput=refresh;
    kind.onchange=()=>{
        if ((dirty() || current) && !confirm('放弃这个阀型尚未保存的修改？')) {kind.value=type;return;}
        type=kind.value;load();
    };
    window.addEventListener('beforeunload',event=>{if(dirty()||current){event.preventDefault();event.returnValue='';}});
    save.onclick=async()=>{
        if (save.disabled) return;
        saving=true;refresh();status.textContent='正在保存…';
        try {
            const payload={type,paths,offset:Number(offset.value),revision:saved().revision};
            const response=await fetch(location.pathname,{method:'POST',headers:{'Content-Type':'application/json',
                'X-CSRFToken':document.querySelector('[name=csrfmiddlewaretoken]').value},body:JSON.stringify(payload)});
            const data=await response.json();
            if (!response.ok || !data.success) throw Error(data.error || '保存失败，请重试。');
            library[type]={paths:paths.slice(),offset:payload.offset,revision:data.revision};
            status.textContent='已保存。重新打开地图即可看到图案。';
        } catch (error) {status.textContent=error.message || '保存失败，请重试。';}
        finally {saving=false;refresh();}
    };
    load();
})();
