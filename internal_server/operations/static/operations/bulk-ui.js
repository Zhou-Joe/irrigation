(function () {
    'use strict';
    const token=()=>crypto.randomUUID();
    const announce=(form,message)=>{let el=form.querySelector('[data-batch-status]');if(!el){el=document.createElement('p');el.dataset.batchStatus='';el.setAttribute('role','status');form.prepend(el);}el.textContent=message;};
    window.FOSBulkLocations={open(){const dialog=document.getElementById('fosBatchDialog');if(!dialog)return;dialog.querySelector('[name=submission_key]').value=token();dialog.showModal();}};
    document.addEventListener('click',event=>{
        if(event.target.closest('[data-batch-open]')){event.preventDefault();window.FOSBulkLocations.open();}
        if(event.target.closest('[data-batch-close]'))event.target.closest('dialog').close();
        if(event.target.matches('[data-check-visible]'))event.target.closest('form').querySelectorAll('[data-batch-choice]').forEach(input=>{if(!input.disabled)input.checked=event.target.checked;});
    });
    async function refreshList({maps=true}={}) {
        const panel=document.getElementById('opLocationResults');
        if(panel){const response=await fetch(location.href,{credentials:'same-origin',cache:'no-store'});if(!response.ok)throw Error('列表更新失败，请重试');const doc=new DOMParser().parseFromString(await response.text(),'text/html');const next=doc.getElementById('opLocationResults');if(next)panel.replaceWith(next);}
        if(maps){await window.FOSLocationMap?.refresh();await window.FOSPestMap?.refresh();}
    }
    window.FOSBulkLocations.refreshResults=refreshList;
    document.addEventListener('submit',async event=>{
        const form=event.target;if(!form.matches('[data-batch-create],[data-batch-share]'))return;
        event.preventDefault();if(form.dataset.busy)return;form.dataset.busy='1';
        let key=form.querySelector('[name=submission_key]');if(key&&!key.value)key.value=token();
        const data=new FormData(form),action=event.submitter?.value||'create';if(form.matches('[data-batch-create]'))data.set('action',action);
        const buttons=[...form.querySelectorAll('button[type=submit]')];buttons.forEach(button=>button.disabled=true);announce(form,'正在处理…');
        try {
            const response=await fetch(form.action,{method:'POST',credentials:'same-origin',body:data,headers:{'X-Requested-With':'XMLHttpRequest'}});
            const result=await response.json();if(!response.ok||!result.success)throw Error(result.errors?.map(error=>'第 '+error.row+' 行：'+error.message).join('\n')||result.message||result.error||'操作未完成');
            if(result.preview){const preview=form.querySelector('[data-batch-preview]');preview.replaceChildren();for(const row of result.rows.slice(0,30)){const line=document.createElement('p');line.textContent=[row.code,row.name,row.kind,row.positioned?'已定位':'待定位'].filter(Boolean).join(' · ');preview.append(line);}announce(form,`检查通过：${result.count} 个地点${result.count>30?'（显示前 30 项）':''}`);}
            else{announce(form,result.message);if(form.matches('[data-batch-create]'))form.reset();if(key)key.value=token();await refreshList();window.IrrigationPWA?.markClean();}
        } catch(error){announce(form,error.message||'网络异常，请保留内容后重试。');}
        finally{delete form.dataset.busy;buttons.forEach(button=>button.disabled=false);}
    });
    document.addEventListener('submit',async event=>{
        const form=event.target;if(!form.matches('[data-location-search]'))return;event.preventDefault();
        const url=new URL(location.href);url.search='';new FormData(form).forEach((value,key)=>url.searchParams.set(key,value));
        try{const response=await fetch(url,{credentials:'same-origin',cache:'no-store'});if(!response.ok)throw Error('搜索暂不可用');const doc=new DOMParser().parseFromString(await response.text(),'text/html');document.getElementById('opLocationResults').replaceWith(doc.getElementById('opLocationResults'));history.replaceState(history.state,'',url);await window.FOSLocationMap?.refresh();}catch(error){announce(form,error.message);}
    });
    document.addEventListener('submit',async event=>{
        const form=event.target;if(!form.matches('[data-location-share]'))return;event.preventDefault();if(form.dataset.busy)return;form.dataset.busy='1';
        const button=event.submitter;if(button)button.disabled=true;announce(form,'正在保存…');
        try{const response=await fetch(form.getAttribute('action')||location.href,{method:'POST',credentials:'same-origin',body:new FormData(form),headers:{'X-Requested-With':'XMLHttpRequest'}});const data=await response.json();if(!response.ok||!data.success)throw Error(data.message||data.error||'保存失败');announce(form,data.message);if(data.edit_url){form.action=data.edit_url;const title=form.closest('section')?.querySelector('h2');if(title)title.textContent='编辑地点';}
            if(form.matches('[data-location-share]')){const page=await fetch(location.href,{credentials:'same-origin',cache:'no-store'});const doc=new DOMParser().parseFromString(await page.text(),'text/html'),list=document.querySelector('.op-sharing'),next=doc.querySelector('.op-sharing');if(list&&next)list.replaceWith(next);}window.opsDirty=false;window.IrrigationPWA?.markClean();}
        catch(error){announce(form,error.message||'网络异常，请保留内容重试。');}finally{delete form.dataset.busy;if(button)button.disabled=false;}
    });
    document.addEventListener('click',async event=>{
        const link=event.target.closest('#opLocationResults .op-pagination a');if(!link)return;event.preventDefault();
        try{const response=await fetch(link.href,{credentials:'same-origin',cache:'no-store'});if(!response.ok)throw Error('列表暂不可用');const doc=new DOMParser().parseFromString(await response.text(),'text/html');document.getElementById('opLocationResults').replaceWith(doc.getElementById('opLocationResults'));history.replaceState(history.state,'',link.href);}catch(error){window.alert(error.message);}
    });
})();
