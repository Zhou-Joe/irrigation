/* Location lists and sharing update in place; the map and creation draft stay mounted. */
(function () {
    'use strict';
    const token=()=>crypto.randomUUID?.()||'10000000-1000-4000-8000-100000000000'.replace(/[018]/g,c=>(c^crypto.getRandomValues(new Uint8Array(1))[0]&15>>c/4).toString(16));
    const feedback=(message,error=false)=>{const box=document.getElementById('opsFeedback');if(box){box.hidden=false;box.textContent=message;box.classList.toggle('error',error);}};
    const announce=(form,message,error=false)=>{let el=form.querySelector('[data-batch-status]');if(!el){el=document.createElement('p');el.dataset.batchStatus='';el.setAttribute('role','status');form.prepend(el);}el.textContent=message;el.classList.toggle('op-error',error);};
    async function reply(response){
        if(response.redirected&&new URL(response.url).pathname==='/login/')throw Error('登录已过期，请重新登录。');
        try{return await response.json();}catch(_){throw Error(response.status===403?'当前账号无权进行此操作。':'保存结果尚未确认，请保留选择后重试。');}
    }
    window.FOSBulkLocations={open(){const dialog=document.getElementById('fosBatchDialog');if(!dialog)return;dialog.querySelector('[name=submission_key]').value=token();dialog.showModal();}};
    function selection(form){
        const choices=[...form.querySelectorAll('[data-batch-choice]:not(:disabled)')],selected=choices.filter(input=>input.checked),all=form.querySelector('[name=all_matching]'),master=form.querySelector('[data-check-visible]');
        if(master){master.checked=choices.length>0&&choices.length===selected.length;master.indeterminate=selected.length>0&&selected.length<choices.length;master.disabled=!choices.length;}
        const count=all?.checked?Number(form.dataset.matchingCount||selected.length):selected.length;
        form.querySelectorAll('[data-selected-count]').forEach(el=>el.textContent=String(count));
        const toolbar=form.querySelector('[data-selection-toolbar]');if(toolbar)toolbar.hidden=!count;
        const targets=[...form.querySelectorAll('input[name=targets]:checked')],summary=form.querySelector('.loc-share-targets > summary > span');
        if(summary)summary.textContent=targets.length===1?targets[0].closest('label').textContent.trim():targets.length?targets.length+' 个接收团队':'接收团队';
        for(const input of choices)input.closest('[data-location-row],.loc-row,.op-location')?.classList.toggle('is-selected',input.checked);
        document.dispatchEvent(new CustomEvent('fos:location-selection',{detail:{count}}));
    }
    function updateSelections(){document.querySelectorAll('[data-batch-share]').forEach(selection);}
    let controller=null,generation=0;
    async function refreshList({maps=true,url=location.href,historyUpdate=false,fit=false}={}){
        const panel=document.getElementById('opLocationResults');if(!panel)return;
        const sequence=++generation;controller?.abort();controller=new AbortController();panel.setAttribute('aria-busy','true');
        try{
            const response=await fetch(url,{credentials:'same-origin',cache:'no-store',signal:controller.signal});
            if(response.redirected&&new URL(response.url).pathname==='/login/')throw Error('登录已过期，请重新登录。');
            if(!response.ok)throw Error('地点列表暂不可用，请重试。');
            const doc=new DOMParser().parseFromString(await response.text(),'text/html'),next=doc.getElementById('opLocationResults');
            if(!next)throw Error('地点列表暂不可用，请重新选择业务视图。');
            if(sequence!==generation)return;
            const controls=document.getElementById('locationControls'),newControls=doc.getElementById('locationControls');
            if(controls&&newControls)controls.replaceWith(newControls);
            panel.replaceWith(next);if(historyUpdate)history.replaceState(history.state,'',url);
            updateSelections();document.dispatchEvent(new CustomEvent('fos:locations-rendered'));
            if(maps)await window.FOSLocationMap?.refresh({fit});
        }catch(error){if(error.name!=='AbortError')throw error;}
        finally{if(sequence===generation)document.getElementById('opLocationResults')?.removeAttribute('aria-busy');}
    }
    window.FOSBulkLocations.refreshResults=refreshList;
    document.addEventListener('change',event=>{
        const form=event.target.closest('[data-batch-share]');if(!form)return;
        if(event.target.matches('[data-check-visible]')){for(const input of form.querySelectorAll('[data-batch-choice]:not(:disabled)'))input.checked=event.target.checked;const all=form.querySelector('[name=all_matching]');if(all)all.checked=false;}
        if(event.target.matches('[name=all_matching]'))for(const input of form.querySelectorAll('[data-batch-choice]:not(:disabled)'))input.checked=event.target.checked;
        if(event.target.matches('[data-batch-choice]')){const all=form.querySelector('[name=all_matching]');if(all)all.checked=false;}
        selection(form);
    });
    document.addEventListener('click',event=>{
        if(event.target.closest('[data-batch-open]')){event.preventDefault();window.FOSBulkLocations.open();}
        if(event.target.closest('[data-batch-close]'))event.target.closest('dialog').close();
        const all=event.target.closest('[data-select-all-matching]');if(all){event.preventDefault();const form=all.closest('[data-batch-share]');form.querySelector('[name=all_matching]').checked=true;form.querySelectorAll('[data-batch-choice]:not(:disabled)').forEach(input=>input.checked=true);selection(form);}
        const clear=event.target.closest('[data-clear-selection]');if(clear){event.preventDefault();const form=clear.closest('[data-batch-share]');form.querySelectorAll('[data-batch-choice],[data-check-visible],[name=all_matching]').forEach(input=>input.checked=false);selection(form);}
    });
    document.addEventListener('submit',async event=>{
        const form=event.target;if(!form.matches('[data-batch-create],[data-batch-share]'))return;
        event.preventDefault();if(form.dataset.busy)return;
        if(form.matches('[data-batch-share]')&&!form.querySelector('[data-batch-choice]:checked')&&!form.querySelector('[name=all_matching]:checked')){announce(form,'请先选择要操作的地点。',true);return;}
        form.dataset.busy='1';let key=form.querySelector('[name=submission_key]');if(key&&!key.value)key.value=token();
        const data=new FormData(form);if(form.matches('[data-batch-create]'))data.set('action',event.submitter?.value||'create');
        const buttons=[...form.querySelectorAll('button[type=submit]')];buttons.forEach(button=>button.disabled=true);announce(form,form.matches('[data-batch-create]')?'正在处理地点…':'正在保存共享设置…');
        try{
            // A field named "action" masks form.action in browsers.
            const response=await fetch(form.getAttribute('action')||location.href,{method:'POST',credentials:'same-origin',body:data,headers:{'X-Requested-With':'XMLHttpRequest'}});
            const result=await reply(response);if(!response.ok||!result.success)throw Error(result.errors?.map(error=>'第 '+error.row+' 行：'+error.message).join('\n')||result.message||result.error||'操作未完成。');
            if(result.preview){const preview=form.querySelector('[data-batch-preview]');preview.replaceChildren();for(const row of result.rows.slice(0,30)){const line=document.createElement('p');line.textContent=[row.code,row.name,row.kind,row.positioned?'已定位':'待定位'].filter(Boolean).join(' · ');preview.append(line);}announce(form,`检查通过：${result.count} 个地点${result.count>30?'（显示前 30 项）':''}`);}
            else{
                if(form.matches('[data-batch-create]'))form.reset();if(key)key.value=token();
                feedback(result.message);announce(form,result.message);window.IrrigationPWA?.markClean();
                try{await refreshList();await window.FOSPestMap?.refresh();}catch(_){feedback(result.message+' 列表尚未更新，请重新查询。');}
            }
        }catch(error){announce(form,error.message||'网络异常，请保留内容后重试。',true);}
        finally{delete form.dataset.busy;buttons.forEach(button=>button.disabled=false);}
    });
    document.addEventListener('submit',async event=>{
        const form=event.target;if(!form.matches('[data-location-search]'))return;event.preventDefault();
        const url=new URL(location.href);url.search='';for(const [key,value]of new FormData(form))if(value)url.searchParams.set(key,value);
        try{await refreshList({url:url.href,historyUpdate:true,fit:true});}catch(error){announce(form,error.message,true);}
    });
    document.addEventListener('change',event=>{const form=event.target.closest('[data-location-search]');if(form&&event.target.matches('select'))form.requestSubmit();});
    document.addEventListener('submit',async event=>{
        const form=event.target;if(!form.matches('[data-location-share]'))return;event.preventDefault();if(form.dataset.busy)return;form.dataset.busy='1';
        const button=event.submitter;if(button)button.disabled=true;announce(form,'正在保存…');
        try{const response=await fetch(form.getAttribute('action')||location.href,{method:'POST',credentials:'same-origin',body:new FormData(form),headers:{'X-Requested-With':'XMLHttpRequest'}}),data=await reply(response);if(!response.ok||!data.success)throw Error(data.message||data.error||'保存失败。');announce(form,data.message);
            const page=await fetch(location.href,{credentials:'same-origin',cache:'no-store'}),doc=new DOMParser().parseFromString(await page.text(),'text/html'),list=document.querySelector('.op-sharing'),next=doc.querySelector('.op-sharing');if(list&&next)list.replaceWith(next);window.opsDirty=false;window.IrrigationPWA?.markClean();}
        catch(error){announce(form,error.message||'网络异常，请保留内容重试。',true);}finally{delete form.dataset.busy;if(button)button.disabled=false;}
    });
    document.addEventListener('click',async event=>{
        const scope=event.target.closest('a[data-location-scope]');
        if(scope&&!event.ctrlKey&&!event.metaKey&&!event.shiftKey&&!event.altKey){
            event.preventDefault();const target=new URL(scope.href,location.href),url=new URL(location.href);
            for(const key of ['ownership','source_team','visibility','page'])url.searchParams.delete(key);
            url.searchParams.set('scope',target.searchParams.get('scope')||'team');
            try{await refreshList({url:url.href,historyUpdate:true,fit:true});}catch(error){feedback(error.message,true);}return;
        }
        const link=event.target.closest('#opLocationResults .op-pagination a');if(!link||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;event.preventDefault();
        try{await refreshList({url:link.href,historyUpdate:true,maps:false});}catch(error){feedback(error.message,true);}
    });
    document.addEventListener('submit',async event=>{
        const form=event.target;if(!form.matches('[data-location-team-visibility]'))return;
        event.preventDefault();if(form.dataset.busy)return;form.dataset.busy='1';
        const data=new FormData(form),key=form.querySelector('[name=submission_key]');
        if(key){if(!key.value)key.value=token();data.set('submission_key',key.value);}
        const button=event.submitter;if(button)button.disabled=true;announce(form,'正在更新本团队可见范围…');
        try{
            const response=await fetch(form.getAttribute('action'),{method:'POST',credentials:'same-origin',body:data,headers:{'X-Requested-With':'XMLHttpRequest'}}),result=await reply(response);
            if(!response.ok||!result.success)throw Error(result.message||'操作未完成。');
            feedback(result.message);window.IrrigationPWA?.markClean();
            const page=await fetch(location.href,{credentials:'same-origin',cache:'no-store'}),doc=new DOMParser().parseFromString(await page.text(),'text/html');
            const old=document.getElementById('locationTeamVisibility'),next=doc.getElementById('locationTeamVisibility');if(old&&next)old.replaceWith(next);
            await window.FOSLocationMap?.refresh();
        }catch(error){announce(form,error.message||'网络异常，请重试。',true);}
        finally{delete form.dataset.busy;if(button)button.disabled=false;}
    });
    if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',updateSelections,{once:true});else updateSelections();
})();
