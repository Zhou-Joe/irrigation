/* Same request key on uncertain retries; user-scoped text drafts, no offline replay. */
(function () {
    'use strict';
    const uid = document.querySelector('.pwa-bottom-nav[data-user-id]')?.dataset.userId;
    if (!uid) return;
    const prefix = 'irrigation-submission-' + uid + '-';
    let storage;
    try { storage = window.sessionStorage; } catch (_) {
        const values = new Map();
        storage = {getItem:key=>values.get(key),setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)};
    }
    const nativeFetch = window.fetch.bind(window);
    const routes = {'/mobile/workorder/v2/':'workorder','/mobile/inventory/v2/':'inventory','/mobile/water-request/v2/':'water_request'};
    const read = kind => {try{return JSON.parse(storage.getItem(prefix+kind));}catch(_){return null;}};
    const save = (kind,value) => {try{if(value)storage.setItem(prefix+kind,JSON.stringify(value));else storage.removeItem(prefix+kind);}catch(_){}};
    const uuid = () => crypto.randomUUID ? crypto.randomUUID() : '10000000-1000-4000-8000-100000000000'.replace(/[018]/g,c=>(c^crypto.getRandomValues(new Uint8Array(1))[0]&15>>c/4).toString(16));
    function notice(kind, pending) {
        let banner=document.getElementById('submissionUncertain');
        if(!banner){banner=document.createElement('div');banner.id='submissionUncertain';banner.setAttribute('role','status');banner.style.cssText='position:fixed;left:12px;right:12px;bottom:calc(76px + env(safe-area-inset-bottom));z-index:15000;background:#fff7df;color:#554512;padding:12px;border:1px solid #dbc88a;border-radius:10px;font:14px system-ui';document.body.append(banner);}
        banner.replaceChildren(document.createTextNode('上次提交结果待确认，当前内容已保留。 '));
        const check=document.createElement('button');check.type='button';check.className='btn-sm btn-secondary';check.textContent='核对结果';banner.append(check);
        check.onclick=async()=>{check.disabled=true;try{const data=await nativeFetch('/api/submissions/'+pending.key+'/',{credentials:'same-origin'}).then(r=>r.json());
            if(data.found){pending.state='saved';save(kind,pending);banner.replaceChildren(document.createTextNode('上次内容已保存。请先查看记录，避免重复填写。 '));const link=document.createElement('a');link.textContent='查看记录';link.href=kind==='inventory'?'/inventory/manage/':kind==='water_request'?'/requests/':'/work-reports/';banner.append(link);}
            else banner.prepend(document.createTextNode('暂未查到完成结果，可用原内容重试。 '));
        }catch(_){banner.prepend(document.createTextNode('网络尚未恢复。 '));}finally{check.disabled=false;}};
    }
    window.IrrigationSubmissions={begin(kind){const previous=read(kind);if(previous?.state==='saved')save(kind,null);else if(previous?.state==='uncertain')notice(kind,previous);}};
    window.fetch=async function(input,init={}) {
        const url=new URL(typeof input==='string'?input:input.url,location.href), kind=routes[url.pathname];
        if(!kind || url.origin!==location.origin || (init.method||'GET').toUpperCase()!=='POST' || !(init.body instanceof FormData))return nativeFetch(input,init);
        const signature=JSON.stringify(Array.from(init.body.entries()).filter(([k])=>!['csrfmiddlewaretoken','submission_key'].includes(k)).map(([k,v])=>[k,v instanceof File?[v.name,v.size,v.lastModified]:v]));
        let pending=read(kind);
        if(pending?.state==='uncertain' && pending.signature!==signature){notice(kind,pending);return new Response(JSON.stringify({success:false,message:'上次提交结果尚未确认；本次修改未提交。请先核对结果。'}),{status:409,headers:{'Content-Type':'application/json'}});}
        if(!pending || pending.signature!==signature)pending={key:uuid(),signature,state:'sending'};
        save(kind,pending);
        const headers=new Headers(init.headers||{});headers.set('X-Submission-Key',pending.key);
        try {
            const response=await nativeFetch(input,{...init,headers});
            let result;try{result=await response.clone().json();}catch(_){pending.state='uncertain';save(kind,pending);notice(kind,pending);return response;}
            if(result.success){pending.state='saved';save(kind,pending);document.getElementById('submissionUncertain')?.remove();clearDraft(kind);}
            else if(result.uncertain || response.status>=500){pending.state='uncertain';save(kind,pending);notice(kind,pending);}
            else save(kind,null);
            return response;
        } catch(error) {pending.state='uncertain';save(kind,pending);notice(kind,pending);throw error;}
    };
    const formKinds={woModalForm:'workorder',invModalForm:'inventory',wrModalForm:'water_request'};
    const draftPrefix='irrigation-text-draft-'+uid+'-';
    function clearDraft(kind){try{localStorage.removeItem(draftPrefix+kind);}catch(_){}}
    // Shared phones must not restore the previous account's text.
    try{if(localStorage.getItem('irrigation-draft-user')!==uid){for(const key of Object.keys(localStorage))if(key.startsWith('irrigation-text-draft-'))localStorage.removeItem(key);localStorage.setItem('irrigation-draft-user',uid);}}catch(_){}
    let timer;
    function saveFormDraft(event){
        const form=event.target.closest('form'),kind=formKinds[form?.id];if(!kind || form.dataset.draftDisabled==='true')return;
        clearTimeout(timer);timer=setTimeout(()=>{const values={};form.querySelectorAll('input,textarea,select').forEach((field,index)=>{
            if(['password','file','hidden','submit'].includes(field.type)||field.name==='csrfmiddlewaretoken')return;
            const key=field.id||field.name||'field-'+index;values[key]={value:field.value,checked:field.checked};
        });try{localStorage.setItem(draftPrefix+kind,JSON.stringify({at:Date.now(),values}));}catch(_){}},350);
    }
    document.addEventListener('input',saveFormDraft);
    document.addEventListener('change',saveFormDraft);
    document.addEventListener('click',event=>{
        const link=event.target.closest('a[href]');
        if(!link || new URL(link.href,location.href).pathname!=='/logout/')return;
        clearTimeout(timer);
        Object.values(formKinds).forEach(kind=>{clearDraft(kind);save(kind,null);});
    });
    document.addEventListener('irrigation:form-open',event=>{
        const kind=event.detail?.kind;window.IrrigationSubmissions.begin(kind);
        const form=document.getElementById(Object.keys(formKinds).find(id=>formKinds[id]===kind));
        if(!form)return;
        form.dataset.draftDisabled=event.detail?.editing?'true':'false';
        if(event.detail?.editing)return;
        let draft;try{draft=JSON.parse(localStorage.getItem(draftPrefix+kind));}catch(_){}
        if(!draft || Date.now()-draft.at>86400000)return;
        if(form.querySelector('[data-restore-draft]'))return;
        const button=document.createElement('button');button.type='button';button.dataset.restoreDraft='true';button.className='btn-sm btn-secondary';button.textContent='恢复文字草稿（照片需重新选择）';form.prepend(button);
        const discard=document.createElement('button');discard.type='button';discard.className='btn-sm btn-secondary';discard.textContent='清除草稿';button.after(discard);
        discard.onclick=()=>{clearDraft(kind);button.remove();discard.remove();};
        button.onclick=()=>{form.querySelectorAll('input,textarea,select').forEach((field,index)=>{const value=draft.values[field.id||field.name||'field-'+index];if(value && !['password','hidden','file','submit'].includes(field.type)){field.value=value.value;if(['checkbox','radio'].includes(field.type))field.checked=value.checked;field.dispatchEvent(new Event('change',{bubbles:true}));}});button.remove();discard.remove();};
    });
    const desktop=document.getElementById('workorder-form');
    if(desktop && !desktop.querySelector('[name="submission_key"]')){
        const key=document.createElement('input');key.type='hidden';key.name='submission_key';key.value=uuid();desktop.append(key);
    }
})();
