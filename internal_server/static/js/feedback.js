(function(root,factory){
    const api=factory();
    if(typeof module==='object'&&module.exports)module.exports=api;
    else{root.FOSFeedback=api;api.mount();}
})(typeof globalThis!=='undefined'?globalThis:this,function(){
    'use strict';
    const MB=1024*1024;
    function validate(photos,attachments){
        if(photos.length>5)return {field:'photos',message:'每条反馈最多上传 5 张照片。'};
        for(const [field,files] of [['photos',photos],['attachments',attachments]])
            if(files.some(file=>!Number.isFinite(file.size)||file.size<=0))return {field,message:'文件为空或大小无效，请重新选择。'};
        if(photos.some(file=>file.size>10*MB))return {field:'photos',message:'每张照片不能超过 10 MB。'};
        if(attachments.some(file=>file.size>50*MB))return {field:'attachments',message:'单个附件不能超过 50 MB。'};
        if(photos.length+attachments.length>10)return {field:'attachments',message:'照片和其他附件合计最多 10 个。'};
        if([...photos,...attachments].reduce((sum,file)=>sum+file.size,0)>100*MB)return {field:'attachments',message:'照片和附件合计不能超过 100 MB。'};
        return null;
    }
    function sizeLabel(size){return size>=MB?(size/MB).toFixed(1)+' MB':size>=1024?Math.ceil(size/1024)+' KB':size+' B';}
    function mount(){
        const form=document.querySelector('[data-feedback-form]');if(!form||form.dataset.feedbackMounted==='yes')return;
        form.dataset.feedbackMounted='yes';
        const text=form.querySelector('textarea'),inputs={photos:form.elements.photos,attachments:form.elements.attachments};
        const count=form.querySelector('[data-feedback-count]'),previews=form.querySelector('[data-feedback-previews]'),error=form.querySelector('[data-feedback-upload-error]');
        let urls=[];const pending=new WeakSet();
        function showCount(){count.textContent=text.value.length+' / 5000';}
        function clearURLs(){urls.forEach(url=>URL.revokeObjectURL(url));urls=[];}
        function icon(name){const svg=document.createElementNS('http://www.w3.org/2000/svg','svg'),use=document.createElementNS(svg.namespaceURI,'use');svg.setAttribute('aria-hidden','true');use.setAttribute('href','#pwa-'+name);svg.append(use);return svg;}
        function showFiles(){
            clearURLs();previews.replaceChildren();
            const groups=Object.fromEntries(Object.entries(inputs).map(([key,input])=>[key,Array.from(input.files||[])]));
            const invalid=validate(groups.photos,groups.attachments);
            for(const [key,input]of Object.entries(inputs))input.setCustomValidity(invalid?.field===key?invalid.message:'');
            error.textContent=invalid?.message||'';error.hidden=!invalid;
            for(const [key,files]of Object.entries(groups))for(const [index,file]of files.slice(0,10).entries()){
                const figure=document.createElement('figure'),caption=document.createElement('figcaption');caption.textContent=file.name;
                if(key==='photos'&&file.type.startsWith('image/')){
                    const image=document.createElement('img');image.src=URL.createObjectURL(file);urls.push(image.src);image.alt='待上传照片 '+(index+1);figure.append(image,caption);
                }else{
                    figure.className='feedback-file-preview';const size=document.createElement('small');size.textContent=sizeLabel(file.size);caption.append(size);figure.append(icon('file'),caption);
                }
                if(typeof DataTransfer!=='undefined'){
                    const remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.setAttribute('aria-label','移除'+(key==='photos'?'照片 ':'附件 ')+file.name);
                    remove.onclick=()=>{const transfer=new DataTransfer();files.forEach((item,i)=>{if(i!==index)transfer.items.add(item);});inputs[key].files=transfer.files;showFiles();};figure.append(remove);
                }
                previews.append(figure);
            }
        }
        text.addEventListener('input',showCount);for(const input of Object.values(inputs))input.addEventListener('change',showFiles);
        form.addEventListener('submit',()=>{if(form.checkValidity()){const button=form.querySelector('button[type=submit]');button.disabled=true;button.textContent='正在提交…';}});
        document.addEventListener('submit',async event=>{
            const action=event.target;if(!action.matches('[data-feedback-action]'))return;event.preventDefault();
            if(pending.has(action))return;if(action.dataset.feedbackConfirm&&!window.confirm(action.dataset.feedbackConfirm))return;
            const entry=action.closest('[data-feedback-entry]'),notice=entry.querySelector('[data-feedback-action-status]'),button=action.querySelector('button[type=submit]');
            pending.add(action);button.disabled=true;notice.hidden=true;
            try{
                const response=await fetch(action.getAttribute('action'),{method:'POST',body:new FormData(action),credentials:'same-origin',headers:{'X-Requested-With':'XMLHttpRequest','Accept':'application/json'}});
                if(response.redirected&&new URL(response.url).pathname==='/login/')throw Error('登录已过期，请重新登录。');
                let data;try{data=await response.json();}catch(_){throw Error('操作未完成，请刷新后重试。');}
                if(!response.ok||!data.success)throw Error(data.message||'操作未完成，请刷新后重试。');
                if(data.file_deleted){const file=action.closest('[data-feedback-file]'),container=file.parentElement;file.remove();if(!container.querySelector('[data-feedback-file]'))container.remove();}
                else if(data.deleted){
                    entry.remove();const total=document.querySelector('[data-feedback-total]');total.textContent=String(Math.max(0,Number(total.textContent)-1));
                    for(const number of document.querySelectorAll('[data-feedback-team-count="'+data.team_id+'"]')){number.textContent=String(Math.max(0,Number(number.textContent)-1));if(number.textContent==='0')number.closest('a').remove();}
                    if(!document.querySelector('[data-feedback-entry]')){const empty=document.createElement('p');empty.className='feedback-empty';empty.textContent=Number(total.textContent)?'本页反馈已删除，可翻页或刷新查看其他反馈。':'暂无反馈。';const stream=document.querySelector('.feedback-stream'),pages=stream.querySelector('.feedback-pagination');if(pages)pages.before(empty);else stream.append(empty);}
                }else if(data.status){
                    const completed=data.status==='completed',badge=entry.querySelector('[data-feedback-status]');badge.textContent=data.label;badge.classList.toggle('is-completed',completed);
                    action.elements.status.value=completed?'open':'completed';button.textContent=completed?'设为未完成':'标记完成';
                }
            }catch(error){notice.textContent=error.message;notice.hidden=false;}
            finally{pending.delete(action);if(button.isConnected)button.disabled=false;}
        });
        window.addEventListener('pagehide',clearURLs);
        window.addEventListener('pageshow',()=>{const button=form.querySelector('button[type=submit]');button.disabled=false;button.textContent='提交反馈 ↗';showFiles();});
        showCount();showFiles();
    }
    return {validate,sizeLabel,mount};
});
