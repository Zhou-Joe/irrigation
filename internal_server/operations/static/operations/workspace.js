/* Refresh role-dependent components in place; never navigate/reload the document. */
(function () {
    'use strict';
    if(!document.getElementById('dashboardWorkspace'))return;
    let changing=false;
    const path=script=>new URL(script.src,location.href).pathname;
    const loaded=new Set([...document.scripts].filter(s=>s.src).map(path));
    const repeat=/\/(map\.js|dashboard\.js|dashboard-modal\.js|pest-map\.js)$/;
    async function runScripts(doc) {
        const holder=document.getElementById('dashboardScripts');holder.replaceChildren();
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
        window.closeNotifPopup?.();
        const nav=doc.getElementById('appNavigation');if(nav)document.getElementById('appNavigation').replaceChildren(...[...nav.childNodes].map(n=>document.importNode(n,true)));
        const old=document.querySelector('.pwa-bottom-nav'),next=doc.querySelector('.pwa-bottom-nav');
        if(old&&next){old.dataset.userId=next.dataset.userId;old.style.cssText=next.style.cssText;
            for(const link of old.querySelectorAll('[data-pwa-nav]')){const counterpart=next.querySelector('[data-pwa-nav="'+link.dataset.pwaNav+'"]');link.hidden=!counterpart||counterpart.hidden;}}
        const list=document.querySelector('.pwa-module-list'),newList=doc.querySelector('.pwa-module-list');
        if(list&&newList)list.replaceChildren(...[...newList.childNodes].map(n=>document.importNode(n,true)));
        for(const id of ['unread-notifications-data','pm-tasks-data']){const current=document.getElementById(id),value=doc.getElementById(id);if(current&&value)current.textContent=value.textContent;}
        window.FOSRefreshNotifications?.();
        document.title=doc.title;
        const preview=!!doc.querySelector('[name=admin_view] option:checked:not([value=admin])');
        const pest=doc.getElementById('dashboardWorkspace')?.dataset.business==='pest-control';
        document.body.classList.toggle('fos-role-preview',pest||preview);
        document.querySelectorAll('.ai-launcher-btn,.ai-chat-panel').forEach(el=>{el.hidden=pest||preview;});
        window.dispatchEvent(new CustomEvent('fos:workspace-changed'));
    }
    document.addEventListener('submit',async event=>{
        const form=event.target;if(!form.matches('.business-switch'))return;
        event.preventDefault();if(changing)return;
        if(window.FOSPestMap?.busy?.()){window.alert('正在提交工单，请完成后再切换。');return;}
        const modalOpen=[...document.querySelectorAll('.v2-modal-container.open,.v2-map-action-bar')].some(el=>el.getClientRects().length);
        if((modalOpen||window.FOSPestMap?.dirty?.()||window.IrrigationPWA?.hasUnsavedChanges?.())&&!confirm('当前表单尚未提交，切换视图会关闭表单。是否继续？'))return;
        changing=true;const button=form.querySelector('button[type=submit]'),label=button.textContent;button.disabled=true;button.textContent='切换中…';
        try {
            const response=await fetch(form.action,{method:'POST',credentials:'same-origin',body:new FormData(form),headers:{'X-Requested-With':'XMLHttpRequest'}});
            const result=await response.json();if(!response.ok||!result.success)throw Error(result.message||result.error||'切换失败');
            const page=await fetch('/',{credentials:'same-origin',cache:'no-store',headers:{'X-Requested-With':'XMLHttpRequest'}});
            if(!page.ok)throw Error('视图暂不可用，请重试切换。');
            const doc=new DOMParser().parseFromString(await page.text(),'text/html'),next=doc.getElementById('dashboardWorkspace'),current=document.getElementById('dashboardWorkspace');
            if(!next)throw Error('地图组件不可用，请重试。');
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
                window.FOSWorkorderModalLifecycle?.refreshRole();
                const oldBatch=document.getElementById('fosBatchDialog'),newBatch=doc.getElementById('fosBatchDialog');
                oldBatch?.remove();if(newBatch)document.getElementById('dashboardWorkspace').append(document.importNode(newBatch,true));
                window.FOSPestMap?.updateRole(doc.getElementById('pestCanSubmit')?.dataset);
                await window.FOSPestMap?.refresh();
                // AI can be loaded when returning from a role view without rebuilding the map.
                for(const script of doc.querySelectorAll('#dashboardScripts > script[src]'))
                    if(/\/(marked\.min|purify\.min|ai-chat-core|genie_arrival|ai-chat)\.js$/.test(path(script))&&!loaded.has(path(script))) {
                        await new Promise((resolve,reject)=>{const el=document.createElement('script');el.src=script.src;for(const a of script.attributes)if(a.name.startsWith('data-'))el.setAttribute(a.name,a.value);el.onload=()=>{loaded.add(path(script));resolve();};el.onerror=reject;document.getElementById('dashboardScripts').append(el);});
                    }
            }
            window.IrrigationPWA?.markClean();
        } catch(error){window.alert(error.message||'切换未完成，请保留当前内容并重试。');}
        finally{changing=false;if(button.isConnected){button.disabled=false;button.textContent=label;}}
    });
})();
