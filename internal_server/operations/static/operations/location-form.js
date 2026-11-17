(function(){
    'use strict';
    const status=form=>form.querySelector('[data-location-status]');
    const say=(form,message,error=false)=>{const el=status(form);if(el){el.textContent=message;el.classList.toggle('op-error',error);}};
    const deleting=new Set();
    function deletionStatus(button,message,error=false){
        const form=button.closest('[data-location-edit]');
        if(form){say(form,message,error);return;}
        const host=button.closest('[data-location-row]')?.querySelector('.loc-row-main')||button.parentElement;
        let feedback=host.querySelector('[data-location-delete-status]');
        if(!feedback){feedback=document.createElement('p');feedback.dataset.locationDeleteStatus='';feedback.className='loc-delete-status';feedback.setAttribute('role','status');host.append(feedback);}
        feedback.textContent=message;feedback.classList.toggle('op-error',error);
        if(error)feedback.scrollIntoView({block:'nearest'});
    }
    document.addEventListener('click',async event=>{
        const button=event.target.closest('[data-location-delete]');if(!button)return;
        event.preventDefault();
        const id=button.dataset.locationId,form=button.closest('[data-location-edit]');
        if(deleting.has(id)||form?.dataset.busy||document.querySelector('[data-batch-share][data-busy]'))return;
        if(!window.confirm('确认删除「'+button.dataset.locationName+'」？该地点及其共享设置将被删除。'))return;
        const data=new FormData();
        data.set('csrfmiddlewaretoken',document.querySelector('[name=csrfmiddlewaretoken]')?.value||'');
        data.set('team',button.dataset.team);data.set('location',id);
        if(!button.dataset.deletionKey)button.dataset.deletionKey=crypto.randomUUID?.()||'10000000-1000-4000-8000-100000000000'.replace(/[018]/g,c=>(c^crypto.getRandomValues(new Uint8Array(1))[0]&15>>c/4).toString(16));
        data.set('submission_key',button.dataset.deletionKey);
        deleting.add(id);button.disabled=true;if(form)form.dataset.busy='delete';
        deletionStatus(button,'正在删除…');
        const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),30000);
        try{
            const response=await fetch(button.dataset.locationDelete,{method:'POST',credentials:'same-origin',body:data,signal:controller.signal,headers:{'X-Requested-With':'XMLHttpRequest'}});
            let result;try{result=await response.json();}catch(_){throw Error(response.status===404?'地点已不存在，或当前账号无权删除。':'删除结果尚未确认，请保留页面后重试。');}
            if(!response.ok||!result.success)throw Error(result.message||result.error||'删除失败，请重试。');
            window.opsDirty=false;window.IrrigationPWA?.markClean();
            document.dispatchEvent(new CustomEvent('fos:location-deleted',{detail:result}));
            if(document.getElementById('opLocationResults')&&window.FOSBulkLocations?.refreshResults){
                window.FOSBulkLocations.forgetLocation(id);
                try{await window.FOSBulkLocations.refreshResults();}
                catch(_){window.location.assign(result.redirect_url);return;}
                const feedback=document.getElementById('opsFeedback');if(feedback){feedback.hidden=false;feedback.textContent=result.message;feedback.classList.remove('error');}
            }else window.location.assign(result.redirect_url);
        }catch(error){deletionStatus(button,error.name==='AbortError'?'删除结果尚未确认，请保留页面后重试。':error.message,true);}
        finally{clearTimeout(timer);deleting.delete(id);button.disabled=false;if(form)delete form.dataset.busy;}
    });
    function buildingFields(form){
        const group=form.querySelector('[data-building-orientations]');if(!group)return;
        const building=form.elements.kind.value==='building';group.hidden=!building;
        const input=form.elements.orientation_options;if(input)input.disabled=!building;
    }
    document.querySelectorAll('[data-location-edit]').forEach(buildingFields);
    document.addEventListener('change',event=>{const form=event.target.closest('[data-location-edit]');if(form&&event.target.name==='kind')buildingFields(form);});
    document.addEventListener('invalid',event=>{
        const form=event.target.closest('[data-location-edit]');if(!form)return;
        const section=event.target.closest('details');if(section)section.open=true;
        say(form,(event.target.labels?.[0]?.textContent||'表单内容')+'：'+event.target.validationMessage,true);
        window.opsDirty=true;
    },true);
    document.addEventListener('input',event=>{
        const form=event.target.closest('[data-location-edit]');if(!form||form.dataset.busy)return;
        const button=form.querySelector('[data-location-save]');if(button)button.textContent='保存地点';window.opsDirty=true;
    });
    document.addEventListener('submit',async event=>{
        const form=event.target;if(!form.matches('[data-location-edit]'))return;
        event.preventDefault();if(form.dataset.busy)return;
        const data=new FormData(form),button=form.querySelector('[data-location-save]');
        form.dataset.busy='1';form.setAttribute('aria-busy','true');if(button){button.disabled=true;button.textContent='保存中…';}say(form,'正在保存…');
        const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),30000);
        try{
            const response=await fetch(form.getAttribute('action')||location.href,{method:'POST',credentials:'same-origin',body:data,signal:controller.signal,headers:{'X-Requested-With':'XMLHttpRequest'}});
            if(response.redirected&&response.url.includes('/login/'))throw Error('登录已过期，请登录后再保存。');
            let result;try{result=await response.json();}catch(_){throw Error(response.status===403?'当前业务或账号无权保存此地点。':response.status===404?'地点已不存在，或当前业务已切换。':'保存结果未确认，请保留内容后重试。');}
            if(!response.ok||!result.success)throw Error(result.message||result.error||'保存失败，请重试。');
            if(result.edit_url)form.setAttribute('action',result.edit_url);
            say(form,'已保存：'+(result.location?.name||'地点')+' · '+new Date().toLocaleTimeString('zh-CN',{hour12:false}));
            if(button)button.textContent='已保存';window.opsDirty=false;window.IrrigationPWA?.markClean();
            document.dispatchEvent(new CustomEvent('fos:location-saved',{detail:result.location}));
        }catch(error){say(form,error.name==='AbortError'?'保存结果未确认，请保留内容后重试。':error.message||'连接失败，请保留内容重试。',true);if(button)button.textContent='重试保存';window.opsDirty=true;}
        finally{clearTimeout(timer);delete form.dataset.busy;form.removeAttribute('aria-busy');if(button)button.disabled=false;}
    });
})();
