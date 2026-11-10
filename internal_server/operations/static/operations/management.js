/* Shared interactions: update results, forms and dialogs without reloading the page. */
(function(){
    'use strict';
    const root=document.querySelector('[data-ops-page]');if(!root)return;
    const receipt=()=>window.crypto?.randomUUID?.()||'10000000-1000-4000-8000-100000000000'.replace(/[018]/g,c=>(c^crypto.getRandomValues(new Uint8Array(1))[0]&15>>c/4).toString(16));
    const csrf=()=>document.querySelector('[name=csrfmiddlewaretoken]')?.value||decodeURIComponent((document.cookie.split('; ').find(c=>c.startsWith('csrftoken='))||'=').split('=').slice(1).join('='));
    const say=(message,error=false,target=null)=>{const element=(target?.isConnected?target:null)||document.getElementById('opsFeedback');if(!element)return;element.hidden=false;element.textContent=message;element.classList.toggle('error',error);element.classList.toggle('op-error',error);};
    async function json(url,options={}){
        const response=await fetch(url,{credentials:'same-origin',cache:'no-store',...options,headers:{'X-Requested-With':'XMLHttpRequest',...(options.headers||{})}});
        if(response.redirected&&new URL(response.url).pathname==='/login/')throw Error('登录已过期，请重新登录。');
        let data;try{data=await response.json();}catch(_){throw Error('请求未完成，请保留输入后重试。');}
        if(!response.ok)throw Error(data.message||data.error||'请求失败，请重试。');return data;
    }
    let generation=0;
    async function refresh(url=location.href,push=false){
        const sequence=++generation;root.setAttribute('aria-busy','true');
        try{const data=await json(url);if(sequence!==generation)return;const target=document.getElementById(data.target||'opsResults');if(data.html&&target)target.innerHTML=data.html;
            if(push)history.replaceState(history.state,'',url);updateExport(url);return data;
        }finally{if(sequence===generation)root.removeAttribute('aria-busy');}
    }
    function updateExport(url){const params=new URL(url,location.href).search;for(const link of root.querySelectorAll('[data-ops-export]'))link.href=link.dataset.opsExport+params;}
    function openDialog(dialog){if(!dialog.open)dialog.showModal();}
    document.addEventListener('click',async event=>{
        const close=event.target.closest('[data-ops-close]');if(close){close.closest('dialog').close();return;}
        const tab=event.target.closest('[data-ops-tab]');if(tab){const group=tab.closest('[data-ops-tabs]');for(const button of group.querySelectorAll('[data-ops-tab]')){const active=button===tab;button.classList.toggle('active',active);button.setAttribute('aria-selected',String(active));document.getElementById(button.dataset.opsTab).hidden=!active;}return;}
        const member=event.target.closest('[data-member-edit]');if(member){const dialog=document.getElementById('memberDialog'),form=dialog.querySelector('form');form.reset();form.elements.username.value=member.dataset.username||'';form.elements.username.readOnly=!!member.dataset.username;form.elements.role.value=member.dataset.role||'field';form.elements.full_name.value=member.dataset.name||'';form.elements.email.value=member.dataset.email||'';form.elements.full_name.readOnly=form.elements.email.readOnly=!!member.dataset.username;form.elements.new_password.disabled=!!member.dataset.username;dialog.querySelector('[data-member-title]').textContent=member.dataset.username?'管理团队身份':'新增成员';say('',false,form.querySelector('[data-ops-form-status]'));openDialog(dialog);return;}
        const planButton=event.target.closest('[data-plan-edit]');if(planButton){const dialog=document.getElementById('planDialog'),form=dialog.querySelector('form');form.reset();form.elements.id.value='';const items=JSON.parse(document.getElementById('pestPlanOptions')?.textContent||'[]'),plan=items.find(p=>String(p.id)===planButton.dataset.planEdit);if(plan){for(const key of ['id','name','frequency_value','frequency_unit','anchor_date','notes'])form.elements[key].value=plan[key];form.elements.active.checked=plan.active;for(const field of ['locations','assignees','nodes'])for(const choice of form.querySelectorAll('[name="'+field+'"]'))choice.checked=(plan[field]||[]).map(String).includes(choice.value);}
            for(const search of form.querySelectorAll('[data-check-search]')){search.value='';for(const row of form.querySelector(search.dataset.checkSearch).children)row.hidden=false;}
            say(plan&&String(plan.catalog_id)!==form.elements.catalog.value?'工作目录已更新，请重新选择当前版本的工作内容。':'',false,form.querySelector('[data-ops-form-status]'));openDialog(dialog);return;}
        const preset=event.target.closest('[data-ops-days]');if(preset){const form=document.getElementById('opsFilter'),end=form.dataset.today,date=new Date(end+'T00:00:00Z');date.setUTCDate(date.getUTCDate()-Number(preset.dataset.opsDays)+1);form.elements.date_from.value=date.toISOString().slice(0,10);form.elements.date_to.value=end;form.requestSubmit();return;}
        const page=event.target.closest('a[data-ops-refresh]');if(page&&!event.metaKey&&!event.ctrlKey&&!event.shiftKey&&!event.altKey){event.preventDefault();const url=new URL(page.href,location.href);if(page.hasAttribute('data-keep-filters')){const current=new URL(location.href);for(const [key,value]of url.searchParams)current.searchParams.set(key,value);if(url.searchParams.has('tab'))current.searchParams.delete('page');url.search=current.search;}
            try{await refresh(url.href,true);}catch(error){say(error.message,true);}return;}
    });
    document.addEventListener('input',event=>{if(event.target.matches('[data-check-search]')){const search=event.target,query=search.value.trim().toLocaleLowerCase();for(const row of document.querySelector(search.dataset.checkSearch).children)row.hidden=!row.textContent.toLocaleLowerCase().includes(query);}});
    document.addEventListener('submit',async event=>{
        const form=event.target;
        if(form.matches('[data-ops-filter]')){event.preventDefault();const url=new URL(form.getAttribute('action')||location.href,location.href);url.search=new URLSearchParams([...new FormData(form)].filter(([,value])=>value!==''));try{await refresh(url.href,true);}catch(error){say(error.message,true);}return;}
        if(!form.matches('[data-ops-post]'))return;event.preventDefault();if(form.dataset.busy)return;
        const data=new FormData(form);if(event.submitter?.name)data.set(event.submitter.name,event.submitter.value);if(!form.dataset.submission)form.dataset.submission=receipt();
        form.dataset.busy='1';const buttons=[...form.querySelectorAll('button[type=submit],button:not([type])')];buttons.forEach(b=>b.disabled=true);const status=form.querySelector('[data-ops-form-status]');say('正在保存…',false,status);
        try{const result=await json(form.getAttribute('action')||location.href,{method:'POST',body:data,headers:{'X-CSRFToken':csrf(),'X-Submission-Key':form.dataset.submission}});if(result.refresh)await refresh(location.href);if(!result.success){say(result.message||'操作未完成。',true,status);return;}delete form.dataset.submission;form.closest('dialog')?.close();say(result.message||'已保存。',false,status?.isConnected&&!form.closest('dialog')?status:null);window.IrrigationPWA?.markClean();}
        catch(error){say(error.message,true,status);}finally{delete form.dataset.busy;buttons.forEach(b=>b.disabled=false);}
    });
    const catalogRoot=document.getElementById('opsCatalog');
    if(catalogRoot){
        let data=null,selected=null;const expanded=new Set(),form=document.getElementById('catalogEdit'),tree=document.getElementById('catalogTree'),search=document.getElementById('catalogSearch');
        const byId=()=>new Map(data.nodes.map(n=>[String(n.id),n]));
        function path(node){const map=byId(),names=[];while(node){names.unshift(node.label);node=map.get(String(node.parent));}return names.join(' / ');}
        function fillEditor(node=null,adding=false){selected=node?String(node.id):null;document.getElementById('catalogPath').textContent=node?path(node):'选择一个工作条目查看或维护。';if(!form)return;form.elements.catalog.value=data.catalog_id||'';form.elements.id.value=adding?'':node?.id||'';form.elements.action.value=adding?'add':'edit';form.elements.label.value=adding?'':node?.label||'';form.elements.kind.value=adding?'node':node?.kind||'node';form.elements.order.value=adding?data.nodes.length:node?.order||0;
            const select=form.elements.parent;select.replaceChildren(new Option('顶级工作类别',''));for(const item of data.nodes)if(String(item.id)!==String(node?.id)||adding)select.add(new Option(path(item),item.id));select.value=adding?(node?.id||''):(node?.parent||'');form.querySelector('[data-catalog-delete]').disabled=!node||adding;
        }
        function draw(){const children=new Map();for(const node of data.nodes){const key=String(node.parent||'');if(!children.has(key))children.set(key,[]);children.get(key).push(node);}const query=search.value.trim().toLocaleLowerCase();
            function matches(node){return node.label.toLocaleLowerCase().includes(query)||(children.get(String(node.id))||[]).some(matches);}
            function renderNode(node){const id=String(node.id),branch=children.get(id)||[],wrap=document.createElement('div'),row=document.createElement('div');row.className='ops-tree-row';row.classList.toggle('selected',id===selected);const toggle=document.createElement('button');toggle.type='button';toggle.className='ops-tree-toggle';toggle.setAttribute('aria-label','展开或收起 '+node.label);toggle.setAttribute('aria-expanded',String(expanded.has(id)||!!query));toggle.innerHTML='<svg class="ui-icon"><use href="#pwa-chevron-right"/></svg>';if(!branch.length){toggle.disabled=true;toggle.style.visibility='hidden';}toggle.onclick=()=>{expanded.has(id)?expanded.delete(id):expanded.add(id);draw();};const button=document.createElement('button');button.className='ops-tree-label';button.type='button';button.textContent=node.label;button.onclick=()=>{fillEditor(node);draw();};row.append(toggle,button);wrap.append(row);if(branch.length&&(expanded.has(id)||query)){const container=document.createElement('div');container.className='ops-tree-children';for(const child of branch)if(!query||matches(child))container.append(renderNode(child));wrap.append(container);}return wrap;}
            tree.replaceChildren();for(const node of children.get('')||[])if(!query||matches(node))tree.append(renderNode(node));if(!tree.children.length)tree.textContent=query?'没有匹配的工作条目。':'暂无工作类别，经理可新增顶级分类。';document.getElementById('catalogCount').textContent=data.nodes.length+' 个工作条目';
        }
        function accept(value){data=value;const version=document.getElementById('catalogVersion');version.replaceChildren(...value.versions.map(v=>new Option(v.time+' · '+v.source,v.id)));version.value=value.catalog_id||'';const current=data.nodes.find(n=>String(n.id)===String(value.selected||selected));fillEditor(current);draw();}
        search.addEventListener('input',draw);
        document.querySelector('[data-catalog-root]')?.addEventListener('click',()=>{if(!data)return;fillEditor(null,true);form.elements.label.focus();draw();});
        document.querySelector('[data-catalog-child]')?.addEventListener('click',()=>{if(!data)return;fillEditor(data.nodes.find(n=>String(n.id)===selected),true);form.elements.label.focus();});
        async function save(body,button){if(button)button.disabled=true;try{const result=await json(catalogRoot.dataset.save,{method:'POST',body,headers:{'X-CSRFToken':csrf()}});accept(result);say(result.message);}catch(error){say(error.message,true);}finally{if(button)button.disabled=false;}}
        form?.addEventListener('submit',event=>{event.preventDefault();if(!form.reportValidity())return;const body=new FormData(form);if(event.submitter?.hasAttribute('data-catalog-delete'))body.set('action','delete');save(body,event.submitter);});
        document.querySelector('[data-catalog-activate]')?.addEventListener('click',event=>{if(!data)return;const body=new FormData();body.set('team',catalogRoot.dataset.team);body.set('catalog',data.catalog_id||'');body.set('version',document.getElementById('catalogVersion').value);body.set('action','activate');save(body,event.currentTarget);});
        json(catalogRoot.dataset.endpoint).then(accept).catch(error=>say(error.message,true));
    }
    updateExport(location.href);
})();
