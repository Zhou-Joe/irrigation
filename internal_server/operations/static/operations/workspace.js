/* Refresh business-dependent components in place; never navigate/reload the document. */
(function () {
    'use strict';
    let changing=false;
    function setBusy(busy){
        for(const form of document.querySelectorAll('.business-switch')){
            form.querySelector('select').disabled=busy;
            form.setAttribute('aria-busy',String(busy));
            const status=form.querySelector('[data-business-status]');if(status)status.textContent=busy?'正在切换业务视图…':'';
        }
    }
    document.addEventListener('change',event=>{
        const select=event.target;if(!select.matches('.business-switch select[name=business]'))return;
        if(changing)return;select.form.requestSubmit();
    });
    const notify=(form,message)=>{if(window.IrrigationPWA?.notify)window.IrrigationPWA.notify(message);else form.title=message;};
    const path=script=>new URL(script.src,location.href).pathname;
    const loaded=new Set([...document.scripts].filter(s=>s.src).map(path));
    const repeat=/\/(map\.js|dashboard\.js|dashboard-modal\.js|pest-map\.js|workorder-chips\.js)$/;
    async function runScripts(doc) {
        let holder=document.getElementById('dashboardScripts');
        if(!holder){holder=document.createElement('div');holder.id='dashboardScripts';holder.hidden=true;document.body.append(holder);}
        holder.replaceChildren();
        for(const original of doc.querySelectorAll('#dashboardScripts > script')) {
            if(original.type==='application/json'){holder.append(document.importNode(original,true));continue;}
            if(original.src) {
                const key=path(original);if(loaded.has(key)&&!repeat.test(key))continue;
                await new Promise((resolve,reject)=>{const script=document.createElement('script');script.src=original.src;script.async=false;
                    for(const attr of original.attributes)if(attr.name.startsWith('data-'))script.setAttribute(attr.name,attr.value);
                    script.onload=()=>{loaded.add(key);resolve();};script.onerror=()=>reject(Error('部分地图组件加载失败，请重试切换。'));holder.append(script);});
            } else {const script=document.createElement('script');script.textContent=original.textContent;holder.append(script);}
        }
    }
    function updateShell(doc) {
        window.AIChat?.beforeWorkspaceChange?.();
        window.closeNotifPopup?.();
        const nav=doc.getElementById('appNavigation');if(nav)document.getElementById('appNavigation').replaceChildren(...[...nav.childNodes].map(n=>document.importNode(n,true)));
        const old=document.querySelector('.pwa-bottom-nav'),next=doc.querySelector('.pwa-bottom-nav');
        if(old&&next){old.dataset.userId=next.dataset.userId;old.style.cssText=next.style.cssText;
            for(const link of old.querySelectorAll('[data-pwa-nav]')){const counterpart=next.querySelector('[data-pwa-nav="'+link.dataset.pwaNav+'"]');link.hidden=!counterpart||counterpart.hidden;}}
        const list=document.querySelector('.pwa-module-list'),newList=doc.querySelector('.pwa-module-list');
        if(list&&newList)list.replaceChildren(...[...newList.childNodes].map(n=>document.importNode(n,true)));
        for(const link of document.querySelectorAll('[data-pwa-nav]')){if(link.dataset.pwaNav==='map')link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');}
        document.querySelector('.pwa-bottom-nav [data-pwa-launcher]')?.removeAttribute('aria-current');
        for(const id of ['unread-notifications-data','pm-tasks-data']){const current=document.getElementById(id),value=doc.getElementById(id);if(current&&value)current.textContent=value.textContent;}
        window.FOSRefreshNotifications?.();
        document.title=doc.title;
        document.body.dataset.page=doc.body.dataset.page;
        if(changing)setBusy(true);
        const allowAI=doc.getElementById('dashboardWorkspace')?.dataset.ai==='yes';
        document.body.classList.toggle('fos-ai-hidden',!allowAI);
        window.dispatchEvent(new CustomEvent('fos:workspace-changed'));
    }
    document.addEventListener('submit',async event=>{
        const form=event.target;if(!form.matches('.business-switch'))return;
        event.preventDefault();if(changing)return;
        const previous=form.dataset.currentBusiness||form.querySelector('select').value;
        if(window.FOSPestMap?.busy?.()||window.FOSWorkorderModalLifecycle?.busy?.()||document.querySelector('form[data-busy]')){form.querySelector('select').value=previous;notify(form,'正在保存，请完成后再切换。');return;}
        // Capture the chosen value before disabling the native select.
        const payload=new FormData(form);changing=true;setBusy(true);
        try {
            const response=await fetch(form.getAttribute('action'),{method:'POST',credentials:'same-origin',body:payload,headers:{'X-Requested-With':'XMLHttpRequest'}});
            const result=await response.json();if(!response.ok||!result.success)throw Error(result.message||result.error||'切换失败');
            const page=await fetch('/',{credentials:'same-origin',cache:'no-store',headers:{'X-Requested-With':'XMLHttpRequest'}});
            if(!page.ok)throw Error('视图暂不可用，请重试切换。');
            const doc=new DOMParser().parseFromString(await page.text(),'text/html'),next=doc.getElementById('dashboardWorkspace');
            let current=document.getElementById('dashboardWorkspace');
            if(!next)throw Error('地图组件不可用，请重试。');
            if(!current){
                current=document.querySelector('[data-ops-page]');
                if(!current){
                    const nodes=[...document.body.childNodes],start=nodes.findIndex(node=>node.nodeType===8&&node.data.trim()==='fos-page-content-start'),end=nodes.findIndex(node=>node.nodeType===8&&node.data.trim()==='fos-page-content-end');
                    if(start<0||end<=start)throw Error('页面组件不可用，请重新打开当前页面。');
                    current=document.createElement('div');nodes[start].after(current);
                    for(const node of nodes.slice(start+1,end))node.remove();
                }
                // Management pages use the same shell; mount the destination map
                // and its styles in place instead of redirecting the document.
                for(const style of doc.querySelectorAll('head link[rel="stylesheet"],head style')){
                    const present=style.tagName==='LINK'?[...document.querySelectorAll('head link[rel="stylesheet"]')].some(s=>s.href===style.href):[...document.querySelectorAll('head style')].some(s=>s.textContent===style.textContent);
                    if(!present)document.head.append(document.importNode(style,true));
                }
                window.FOSLocationMap?.destroy?.();
                window.FOSLocationEditor?.destroyAll?.();
                history.replaceState(history.state,'','/');
            }
            const mounted=current.dataset.business==='pest-control'?window.FOSPestMap:window.FOSDashboardLifecycle&&window.FOSMapLifecycle;
            const same=current.dataset.business===next.dataset.business&&current.dataset.mounted!=='no'&&!!mounted;
            updateShell(doc);
            if(!same) {
                const map=window._map;window.FOSMapInitialView=map?{center:map.getCenter(),zoom:map.getZoom()}:null;
                window.FOSPestMap?.destroy();window.FOSWorkorderModalLifecycle?.destroy();window.FOSDashboardLifecycle?.destroy();window.FOSMapLifecycle?.destroy();window.FOSMapActions?.destroy();
                window.FOSPestMap=window.FOSMapLifecycle=window.FOSDashboardLifecycle=window.FOSWorkorderModalLifecycle=null;
                window.zonesData=[];window._zoneById={};window._dashboardZonesLayer=null;
                const replacement=document.importNode(next,true);replacement.dataset.mounted='no';current.replaceWith(replacement);await runScripts(doc);replacement.dataset.mounted='yes';
                if(window.FOSMapInitialView&&window._map)window._map.setView(window.FOSMapInitialView.center,window.FOSMapInitialView.zoom);
                window.FOSMapInitialView=null;
            } else {
                // The map stays mounted, but account capabilities may have
                // changed. Chat reads these attributes after the switch.
                for(const name of ['data-ai','data-quotes-enabled']){
                    const value=next.getAttribute(name);
                    if(value===null)current.removeAttribute(name);else current.setAttribute(name,value);
                }
                window.FOSWorkorderModalLifecycle?.refreshRole();
                const oldBatch=document.getElementById('fosBatchDialog'),newBatch=doc.getElementById('fosBatchDialog');
                oldBatch?.remove();if(newBatch)document.getElementById('dashboardWorkspace').append(document.importNode(newBatch,true));
                window.FOSPestMap?.updateRole(doc.getElementById('pestCanSubmit')?.dataset);
                await window.FOSPestMap?.refresh();
                await window.FOSDashboardLifecycle?.refresh?.();
                // Load newly available account tools without rebuilding the map.
                for(const script of doc.querySelectorAll('#dashboardScripts > script[src]'))
                    if(/\/(marked\.min|purify\.min|ai-chat-core|genie_arrival|inventory-move|inventory-quotes|ai-chat)\.js$/.test(path(script))&&!loaded.has(path(script))) {
                        await new Promise((resolve,reject)=>{const el=document.createElement('script');el.src=script.src;for(const a of script.attributes)if(a.name.startsWith('data-'))el.setAttribute(a.name,a.value);el.onload=()=>{loaded.add(path(script));resolve();};el.onerror=reject;document.getElementById('dashboardScripts').append(el);});
                    }
            }
            window.IrrigationPWA?.markClean();
        } catch(error){if(form.isConnected)form.querySelector('select').value=previous;notify(form,error.message||'切换未完成，请重试。');}
        finally{window.AIChat?.afterWorkspaceChange?.();changing=false;setBusy(false);}
    });
})();
