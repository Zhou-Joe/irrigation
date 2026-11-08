(function(root,factory){
    const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.FOSMapLocationCreate=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
    'use strict';
    const kinds=new Set(['zone','building','floor','room','monitoring','other']);
    function draft(values,point){
        const name=String(values.name||'').trim(),code=String(values.code||'').trim(),kind=values.kind||'building';
        if(!name||name.length>150)throw Error('请填写地点名称（最多 150 字）。');
        if(code.length>100||!kinds.has(kind))throw Error('请检查地点编号和类型。');
        if(!point||point.length!==2||!point.every(v=>typeof v==='number'&&Number.isFinite(v))||Math.abs(point[0])>90||Math.abs(point[1])>180)throw Error('请先在地图上点选位置。');
        return {name,code,kind,latitude:point[0].toFixed(7),longitude:point[1].toFixed(7)};
    }
    function createSession({team,csrf,send,uuid=()=>crypto.randomUUID()}){
        let busy=false,key='',fingerprint='',count=0;
        return {busy:()=>busy,count:()=>count,async save(values,point){
            if(busy)throw Error('正在保存，请稍候。');
            const item=draft(values,point),next=JSON.stringify(item);
            if(next!==fingerprint){fingerprint=next;key=uuid();}
            const data=new FormData();data.set('team',String(team));data.set('csrfmiddlewaretoken',csrf);data.set('submission_key',key);
            const quote=value=>'"'+String(value).replace(/"/g,'""')+'"';
            data.set('rows',[item.name,item.code,item.kind,'',item.latitude,item.longitude,''].map(quote).join('\t'));
            busy=true;
            try{
                const response=await send(data),result=await response.json();
                if(!response.ok||!result.success)throw Error(result.message||result.error||'保存失败，请重试。');
                count++;fingerprint='';key='';return {...item,id:result.ids[0]};
            }finally{busy=false;}
        }};
    }
    function mount({map,panel,markers,L,onSaved,onOpen=()=>{},onClose=()=>{}}){
        if(!panel)return {open(){},close(){},pick(){return false;},active:()=>false,busy:()=>false,destroy(){}};
        const form=panel.querySelector('form'),name=form.elements.name,kind=form.elements.kind,status=panel.querySelector('[data-create-status]'),position=panel.querySelector('[data-create-position]');
        const session=createSession({team:panel.dataset.team,csrf:form.elements.csrfmiddlewaretoken.value,
            send:async data=>{
                const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),30000);
                try{const response=await fetch(form.action,{method:'POST',credentials:'same-origin',body:data,signal:controller.signal,headers:{'X-Requested-With':'XMLHttpRequest'}}),result=await response.json();return {ok:response.ok,json:async()=>result};}
                catch(error){if(error.name==='AbortError')throw Error('保存结果尚未确认，请保留内容后重试。');throw error;}
                finally{clearTimeout(timer);}
            }});
        let active=false,point=null,pin=null,disposed=false;
        function clearPin(){if(pin){map.removeLayer(pin);pin=null;}}
        function showPin(){clearPin();if(point)pin=markers.marker(L,{kind:kind.value,name:name.value||'新地点'},point).addTo(map);}
        function pick(value){
            if(!active)return false;if(session.busy())return true;
            point=[value.lat,value.lng];showPin();position.textContent='位置已选 · 可在地图上点选调整';
            if(matchMedia('(min-width:769px)').matches)name.focus({preventScroll:true});return true;
        }
        function close(){if(session.busy())return;active=false;point=null;clearPin();panel.hidden=true;panel.ownerDocument.body.classList.remove('fos-location-creating');map.getContainer().classList.remove('pest-create-mode');window.IrrigationPWA?.markClean();onClose();}
        panel.querySelector('[data-create-close]').onclick=close;
        kind.onchange=showPin;name.oninput=showPin;
        const block=event=>L.DomEvent.stopPropagation(event);
        for(const type of ['click','dblclick','pointerdown','touchstart','wheel'])panel.addEventListener(type,block);
        form.onsubmit=async event=>{
            event.preventDefault();if(session.busy()||!form.reportValidity())return;
            const values={name:name.value,kind:kind.value,code:form.elements.code.value};
            const controls=[...form.querySelectorAll('input,select,button')],button=form.querySelector('[type=submit]');
            controls.forEach(el=>el.disabled=true);button.textContent='保存中…';status.textContent='正在保存地点…';
            try{
                const item=await session.save(values,point);if(disposed)return;
                // The next point is a fresh draft; keep the chosen type for repeated placement.
                name.value='';form.elements.code.value='';point=null;clearPin();
                position.textContent='在地图上点选下一个位置';status.textContent=`已保存「${item.name}」 · 本次已添加 ${session.count()} 个`;
                window.IrrigationPWA?.markClean();await onSaved(item);
            }catch(error){if(!disposed)status.textContent=error.message||'保存结果尚未确认，请保留内容后重试。';}
            finally{if(!disposed){controls.forEach(el=>el.disabled=false);button.textContent='保存并继续';}}
        };
        return {active:()=>active,busy:session.busy,pick,close,
            open(){if(disposed||active||onOpen()===false)return;active=true;panel.hidden=false;panel.ownerDocument.body.classList.add('fos-location-creating');position.textContent='在地图上点选位置';status.textContent='点选位置、输入名称，保存后可继续添加。';map.closePopup();map.getContainer().classList.add('pest-create-mode');},
            destroy(){disposed=true;active=false;clearPin();panel.ownerDocument.body.classList.remove('fos-location-creating');map.getContainer().classList.remove('pest-create-mode');for(const type of ['click','dblclick','pointerdown','touchstart','wheel'])panel.removeEventListener(type,block);}};
    }
    return {draft,createSession,mount};
});
