(function (root,factory) {
    const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.FOSLocationPicker=api;
})(typeof globalThis!=='undefined'?globalThis:this,function () {
    'use strict';
    function createState(options,preset=[]) {
        const entries=new Map(options.map(p=>[String(p.id),{...p,id:String(p.id)}]));
        const selected=new Set(preset.map(String).filter(id=>entries.has(id)));
        return {all:()=>[...entries.values()],selected:()=>[...selected],
            matches(query='',kind='') {const q=query.trim().toLocaleLowerCase();return [...entries.values()].filter(p=>(!kind||p.kind===kind)&&(!q||(p.code+' '+p.name).toLocaleLowerCase().includes(q)));},
            toggle(id,value) {id=String(id);if(!entries.has(id))return false;const checked=value===undefined?!selected.has(id):value;if(checked)selected.add(id);else selected.delete(id);return true;},
            has:id=>selected.has(String(id)),label:id=>entries.get(String(id)),clear:()=>selected.clear(),
            selectMatches(query,kind,value=true) {this.matches(query,kind).forEach(p=>this.toggle(p.id,value));}
        };
    }
    function mount(form,options,preset,onChange,enterMap) {
        const state=createState(options,preset),doc=form.ownerDocument;
        const overlay=doc.createElement('div');overlay.className='v2-sheet-overlay';overlay.id='pestLocationPicker';
        overlay.innerHTML='<section class="v2-sheet"><div class="pest-picker-head"><strong>选择作业地点</strong><button type="button" data-picker-close aria-label="关闭">×</button></div><div class="v2-draw-tabs"><button type="button" class="v2-draw-tab active" data-picker-tab="search">搜索</button><button type="button" class="v2-draw-tab" data-picker-tab="kind">地点类型</button><button type="button" class="v2-draw-tab" data-picker-tab="map">地图点选</button></div><div class="pest-picker-body"><input class="v2-input" type="search" placeholder="搜索地点编号或名称…" data-picker-search><select class="v2-select" data-picker-kind hidden><option value="">全部类型</option><option value="zone">室外区域</option><option value="building">建筑</option><option value="floor">楼层</option><option value="room">房间</option><option value="monitoring">监测点</option><option value="other">其他地点</option></select><div class="wo-zone-search-bar"><span data-picker-count></span><button type="button" class="wo-zsb-btn" data-picker-all>全选筛选结果</button><button type="button" class="wo-zsb-btn clear" data-picker-clear>清除</button></div><div class="wo-zone-search-results" data-picker-list></div><button type="button" class="v2-btn-cancel" data-picker-more>加载更多</button></div><div class="v2-modal-footer"><button type="button" class="v2-btn-submit" data-picker-confirm>确认地点</button></div></section>';
        doc.body.append(overlay);
        const query=overlay.querySelector('[data-picker-search]'),kind=overlay.querySelector('[data-picker-kind]');let limit=50;
        function sync() {
            const ids=state.selected(),values=form.querySelector('#pestPlaceValues');values.replaceChildren();
            for(const id of ids){const input=doc.createElement('input');input.type='hidden';input.name='locations';input.value=id;values.append(input);}
            const names=ids.slice(0,2).map(id=>state.label(id).name).join('、');
            form.querySelector('#pestPlaceSummary').textContent=ids.length?`已选 ${ids.length} 个地点 · ${names}${ids.length>2?'…':''}`:'选择作业地点';
            render();
        }
        function render() {
            const matches=state.matches(query.value,kind.hidden?'':kind.value),list=overlay.querySelector('[data-picker-list]');list.replaceChildren();
            overlay.querySelector('[data-picker-count]').textContent=`筛选 ${matches.length} 项 · 已选 ${state.selected().length}`;
            for(const place of matches.slice(0,limit)) {
                const row=doc.createElement('button');row.type='button';row.className='wo-zone-search-item'+(state.has(place.id)?' selected':'');row.setAttribute('aria-pressed',String(state.has(place.id)));
                const label=doc.createElement('span');label.textContent=(place.code?place.code+' · ':'')+place.name;
                const check=doc.createElement('span');check.className='wo-zs-check';check.textContent=state.has(place.id)?'✓':'';row.append(label,check);
                row.onclick=()=>{state.toggle(place.id);sync();onChange();};list.append(row);
            }
            if(!matches.length){const empty=doc.createElement('p');empty.textContent='没有匹配的地点';list.append(empty);}
            overlay.querySelector('[data-picker-more]').hidden=matches.length<=limit;
        }
        function close(){overlay.style.display='none';}
        const api={state,sync,open(){limit=50;render();overlay.style.display='flex';},close,destroy(){overlay.remove();}};
        form.querySelector('#pestPlaceTrigger').onclick=api.open;
        query.oninput=()=>{limit=50;render();};kind.onchange=()=>{limit=50;render();};
        overlay.querySelector('[data-picker-more]').onclick=()=>{limit+=50;render();};
        overlay.querySelector('[data-picker-close]').onclick=close;overlay.querySelector('[data-picker-confirm]').onclick=close;
        overlay.querySelector('[data-picker-all]').onclick=()=>{state.selectMatches(query.value,kind.hidden?'':kind.value);sync();onChange();};
        overlay.querySelector('[data-picker-clear]').onclick=()=>{state.selectMatches(query.value,kind.hidden?'':kind.value,false);sync();onChange();};
        overlay.querySelectorAll('[data-picker-tab]').forEach(button=>button.onclick=()=>{
            if(button.dataset.pickerTab==='map'){close();enterMap(api);return;}
            kind.hidden=button.dataset.pickerTab!=='kind';limit=50;
            overlay.querySelectorAll('[data-picker-tab]').forEach(b=>b.classList.toggle('active',b===button));render();
        });
        overlay.onclick=event=>{if(event.target===overlay)close();};sync();return api;
    }
    return {createState,mount};
});
