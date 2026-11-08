/* Shared irrigation/pest map controls: one layout and one set of interactions. */
(function () {
    'use strict';
    let current;
    window.FOSScopedEffects=function () {
        let stopped=false;const cleanup=[];
        return {get stopped(){return stopped;},listen(target,type,callback,options){if(!target?.addEventListener)return;const fn=(...args)=>{if(!stopped)callback(...args);};target.addEventListener(type,fn,options);cleanup.push(()=>target.removeEventListener?.(type,fn,options));},
            interval(callback,delay){const id=setInterval(()=>{if(!stopped)callback();},delay);cleanup.push(()=>clearInterval(id));return id;},
            timeout(callback,delay){const id=setTimeout(()=>{if(!stopped)callback();},delay);cleanup.push(()=>clearTimeout(id));return id;},
            destroy(){stopped=true;cleanup.splice(0).forEach(fn=>fn());}};
    };
    // A disposed form must not write a late response into its replacement.
    window.FOSScopedRequests=function () {
        let epoch=0,stopped=false,writes=0;const pending=new Set();
        const aborted=()=>Object.assign(new Error('Form context changed'),{name:'AbortError'});
        function reset(){epoch++;for(const controller of pending)controller.abort();pending.clear();}
        return {busy:()=>writes>0,reset,destroy(){stopped=true;reset();},
            async fetch(url,options={}) {
                if(stopped)throw aborted();
                const version=epoch,controller=new AbortController(),write=!/^(GET|HEAD)$/i.test(options.method||'GET');
                pending.add(controller);if(write)writes++;let released=false;
                const release=()=>{if(released)return;released=true;pending.delete(controller);if(write)writes--;};
                try {
                    const response=await window.fetch(url,{...options,signal:controller.signal});
                    const json=response.json.bind(response);
                    response.json=()=>json().then(data=>{if(stopped||epoch!==version)throw aborted();return data;}).finally(release);
                    return response;
                } catch(error){release();throw error;}
            }};
    };
    function mount(items) {
        if(current)current.destroy();
        const desktop=!matchMedia('(max-width:768px)').matches;
        const wrap=document.createElement('div');wrap.className='fab-mobile-wrap';wrap.style.cssText=desktop?'position:fixed;right:24px;bottom:24px;z-index:999;':'position:relative;z-index:999;';
        const menu=document.createElement('div');menu.id='mapShortcuts';menu.className='map-shortcut-menu';
        let open=desktop;menu.hidden=!open;
        const fab=document.createElement('button');fab.className='fab-btn map-tool-btn'+(open?' active':'');fab.type='button';fab.title='功能菜单';fab.setAttribute('aria-controls','mapShortcuts');fab.setAttribute('aria-expanded',String(open));fab.innerHTML=window.uiIcon('menu');
        function setItems(values) {
            menu.replaceChildren();
            for(const item of values) {
                const link=document.createElement('a');link.href=item.url||'#';
                if(!item.url)link.onclick=event=>{event.preventDefault();event.stopPropagation();item.action?.();};
                const icon=document.createElement('span');icon.className='map-action-icon';icon.innerHTML=window.uiIcon(item.icon);
                const text=document.createElement('span');text.style.cssText='font-size:0.75em;margin-top:2px';text.textContent=item.label;
                link.append(icon,text);link.style.cssText='display:flex;flex-direction:column;align-items:center;justify-content:center;width:60px;height:60px;border-radius:14px;background:#fff;color:#222;text-decoration:none;box-shadow:0 2px 8px rgba(0,0,0,0.12);opacity:1;transform:translateY(0);transition:opacity 0.2s,transform 0.2s;pointer-events:auto;';menu.append(link);
            }
        }
        fab.onclick=()=>{open=!open;menu.hidden=!open;fab.classList.toggle('active',open);fab.setAttribute('aria-expanded',String(open));
            [...menu.children].forEach((el,i)=>{el.style.opacity=open?'1':'0';el.style.transform=open?'translateY(0)':'translateY(-10px)';el.style.transitionDelay=(open?i*.05:(menu.children.length-1-i)*.03)+'s';el.style.pointerEvents=open?'auto':'none';});};
        wrap.append(fab,menu);document.body.append(wrap);setItems(items);
        const outside=event=>{if(open&&!wrap.contains(event.target))fab.click();};document.addEventListener('click',outside);
        const timers=[];
        if(!desktop) {
            const cluster=document.getElementById('mobileBtnCluster');
            if(cluster){for(const id of ['mapLayerPanel','mapFilterWidget']){const el=document.getElementById(id);if(el)cluster.append(el);}cluster.append(wrap);
                const move=()=>{const button=document.querySelector('.locate-btn'),slot=document.getElementById('mobileLocateSlot');if(button&&slot&&!slot.contains(button)){slot.append(button);button.style.margin='0';}};
                move();timers.push(setTimeout(move,500),setTimeout(move,1500));}
        }
        current={setItems,destroy(){timers.forEach(clearTimeout);document.removeEventListener('click',outside);wrap.remove();}};
        return current;
    }
    window.FOSMapActions={mount,setItems:items=>current?.setItems(items),destroy:()=>current?.destroy()};
})();
