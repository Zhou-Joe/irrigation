(function(){
    'use strict';
    const status=form=>form.querySelector('[data-location-status]');
    const say=(form,message,error=false)=>{const el=status(form);if(el){el.textContent=message;el.classList.toggle('op-error',error);}};
    document.addEventListener('invalid',event=>{
        const form=event.target.closest('[data-location-edit]');if(!form)return;
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
