/* Same request key on uncertain retries; user-scoped text drafts, no offline replay. */
(function () {
    'use strict';
    const uid = document.querySelector('.pwa-bottom-nav[data-user-id]')?.dataset.userId;
    if (!uid) return;
    const prefix = 'irrigation-submission-' + uid + '-';
    const memory = new Map();
    let storage;
    try { storage = window.sessionStorage; } catch (_) {}
    const nativeFetch = window.fetch.bind(window);
    const routes = {'/mobile/workorder/v2/':'workorder','/mobile/inventory/v2/':'inventory','/mobile/water-request/v2/':'water_request'};
    const forms = new Map();
    const sending = new Set();
    function read(kind) {
        if (memory.has(kind)) return memory.get(kind);
        try {
            const value = JSON.parse(storage?.getItem(prefix + kind) || 'null');
            memory.set(kind, value);
            return value;
        } catch (_) { return null; }
    }
    function save(kind, value) {
        memory.set(kind, value);
        try {
            if (value) storage?.setItem(prefix + kind, JSON.stringify(value));
            else storage?.removeItem(prefix + kind);
        } catch (_) {}
    }
    const uuid = () => crypto.randomUUID ? crypto.randomUUID() : '10000000-1000-4000-8000-100000000000'.replace(/[018]/g,c=>(c^crypto.getRandomValues(new Uint8Array(1))[0]&15>>c/4).toString(16));
    function scope(kind, team) {
        if (kind !== 'workorder') return kind;
        // Older tabs stored irrigation and pest receipts under the same name.
        const legacy = read(kind);
        if (legacy?.signature) {
            const fields = new Map(JSON.parse(legacy.signature));
            if (fields.has('catalog') && fields.get('team')) {
                const target = 'pest-workorder-' + fields.get('team');
                if (!read(target)) save(target, legacy);
                save(kind, null);
            }
        }
        return team ? 'pest-workorder-' + team : kind;
    }
    function notice(kind, pending) {
        let banner = document.getElementById('submissionUncertain');
        if (!banner) {
            banner = document.createElement('div');
            banner.id = 'submissionUncertain';
            banner.setAttribute('role', 'status');
        }
        banner.dataset.kind = kind;
        const form = forms.get(kind);
        const container = form?.isConnected && form.closest('.v2-modal-container');
        const footer = container?.querySelector?.('.v2-modal-footer');
        if (footer) footer.before(banner);
        else if (form?.isConnected) form.prepend(banner);
        else document.body.append(banner);
        const message = document.createTextNode('上次提交结果待确认，当前内容已保留。 ');
        const check = document.createElement('button');
        check.type = 'button';
        check.className = 'btn-sm btn-secondary';
        check.textContent = '核对结果';
        banner.replaceChildren(message, check);
        check.onclick = async () => {
            check.disabled = true;
            const current = () => read(kind) === pending && pending.state === 'uncertain' && !sending.has(kind) && banner.contains(check);
            try {
                const response = await nativeFetch('/api/submissions/' + pending.key + '/', {credentials:'same-origin', cache:'no-store'});
                if (!response.ok) throw Error();
                const data = await response.json();
                if (!current()) return;
                if (data.found === true) {
                    save(kind, {...pending, state:'saved'});
                    const link = document.createElement('a');
                    link.textContent = '查看记录';
                    link.href = data.kind === 'pest-workorder' ? '/work-reports/' + data.result.report_id + '/' :
                        kind === 'inventory' ? '/inventory/manage/' : kind === 'water_request' ? '/requests/' : '/work-reports/';
                    banner.replaceChildren(document.createTextNode('上次内容已保存。 '), link);
                } else if (data.found === false) {
                    // A late commit must still collide with this same key on retry.
                    save(kind, {...pending, state:'checked-missing'});
                    banner.replaceChildren(document.createTextNode('暂未查到已保存的记录，可以修改内容并重试。'));
                } else throw Error();
            } catch (_) {
                if (current()) message.textContent = '核对失败，请恢复连接或重新登录后再核对。 ';
            } finally { check.disabled = false; }
        };
    }
    function begin(kind, form) {
        kind = scope(kind, form?.elements.namedItem('catalog') && form.elements.namedItem('team')?.value);
        if (form) forms.set(kind, form);
        let pending = read(kind);
        if (pending?.state === 'sending' && !sending.has(kind)) {
            pending = {...pending, state:'uncertain'};
            save(kind, pending);
        }
        if (pending?.state === 'uncertain') notice(kind, pending);
        else {
            if (pending?.state === 'saved') save(kind, null);
            document.getElementById('submissionUncertain')?.remove();
        }
    }
    window.IrrigationSubmissions = {begin};
    window.fetch = async function(input, init = {}) {
        const url = new URL(typeof input === 'string' ? input : input.url, location.href);
        const route = routes[url.pathname];
        if (!route || url.origin !== location.origin || (init.method || 'GET').toUpperCase() !== 'POST' || !(init.body instanceof FormData)) return nativeFetch(input, init);
        const body = init.body;
        const kind = scope(route, body.has('catalog') && body.get('team'));
        const signature = JSON.stringify(Array.from(body.entries()).filter(([key]) => !['csrfmiddlewaretoken','submission_key'].includes(key)).map(([key,v]) => [key,v instanceof File ? [v.name,v.size,v.lastModified] : v]));
        const formKey = body.get('submission_key');
        const previous = read(kind);
        const conflict = message => new Response(JSON.stringify({success:false, message}), {status:409, headers:{'Content-Type':'application/json'}});
        if (sending.has(kind)) return conflict('正在提交，请等候当前结果。');
        if (previous?.state === 'uncertain' && previous.signature !== signature) {
            notice(kind, previous);
            return conflict('本次修改尚未提交，请先核对上次提交结果。');
        }
        const retry = previous && (['uncertain','checked-missing'].includes(previous.state) ||
            previous.signature === signature && (!formKey || previous.formKey === formKey));
        const pending = {key:retry ? previous.key : formKey || uuid(), formKey, signature, state:'sending'};
        sending.add(kind);
        save(kind, pending);
        const headers = new Headers(init.headers || {});
        headers.set('X-Submission-Key', pending.key);
        const uncertain = () => {
            pending.state = 'uncertain';
            save(kind, pending);
            notice(kind, pending);
        };
        try {
            const response = await nativeFetch(input, {...init, headers});
            let result;
            try { result = await response.clone().json(); } catch (_) { uncertain(); return response; }
            if (response.ok && result.success) {
                save(kind, {...pending, state:'saved'});
                const banner = document.getElementById('submissionUncertain');
                if (banner?.dataset.kind === kind) banner.remove();
                if (route === kind) clearDraft(kind);
            } else if (result.uncertain || response.status >= 500) uncertain();
            else if (previous && ['uncertain','checked-missing'].includes(previous.state)) {
                // Validation rejects this attempt only. The earlier request may still arrive.
                save(kind, previous);
                if (previous.state === 'uncertain') notice(kind, previous);
            } else save(kind, null);
            return response;
        } catch (error) { uncertain(); throw error; }
        finally { sending.delete(kind); }
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
        Object.values(formKinds).forEach(clearDraft);
        try { Object.keys(storage || {}).filter(key => key.startsWith(prefix)).forEach(key => storage.removeItem(key)); } catch (_) {}
        for (const kind of memory.keys()) save(kind, null);
    });
    document.addEventListener('irrigation:form-open',event=>{
        const kind=event.detail?.kind;
        const form=document.getElementById(Object.keys(formKinds).find(id=>formKinds[id]===kind));
        if(!form)return;
        begin(kind, form);
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
