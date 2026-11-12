/* Accessible streaming assistant UI. Business actions remain server-side. */
(function () {
    'use strict';
    const core = window.AIChatCore;
    if (!core) return;
    const mascotBaseURL = document.currentScript?.dataset.mascotBase || '/static/ai/engenie/';
    const quotesDefault = document.currentScript?.dataset.quotesEnabled === 'yes';
    let threadId = null, activeRun = null, sequence = 0, panelOpen = false, expanded = false, follow = true;
    let historyDay = null, historyTimer = null, historyDeadline = null;
    let panelMotion = null, motionVersion = 0;
    let workspaceAvailable=true,repositionLauncher=()=>{};
    let availabilityRequest = null;
    let availabilityVersion = 0;
    let pendingAttachments = [], attachmentGeneration = 0, uploadWorkerGeneration = null, attachmentSequence = 0;
    let historyRestoreVersion = 0, restoringHistory = false;
    const responseViews = new Map();
    const attachmentLimit = 5, attachmentMaxSize = 10 * 1024 * 1024;
    const attachmentAccept = '.txt,.md,.log,.json,.csv,.xlsx,.docx,.pdf,.png,.jpg,.jpeg,.webp';
    const byId = id => document.getElementById(id);
    const icon = name => window.uiIcon(name);
    const node = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
    function mascot(pose = 'reply') {
        const frame = node('span', 'ai-mascot' + (pose === 'welcome' ? ' ai-mascot-full' : ''));
        frame.setAttribute('aria-hidden', 'true');
        if (pose === 'welcome') {
            const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
            svg.setAttribute('viewBox', '0 0 40 40'); svg.setAttribute('aria-hidden', 'true');
            svg.dataset.genieArrival = ''; svg.dataset.duration = '2560';
            for (const theme of ['light', 'dark']) {
                svg.dataset[theme + 'Intro'] = mascotBaseURL + 'engenie-arrival-' + theme + '.gif';
                svg.dataset[theme + 'Still'] = mascotBaseURL + 'engenie-idle-' + theme + '.png';
            }
            const idle = document.createElementNS('http://www.w3.org/2000/svg', 'image');
            idle.dataset.genieIdle = ''; idle.setAttribute('href', svg.dataset.lightStill);
            idle.setAttribute('width', '40'); idle.setAttribute('height', '40');
            svg.append(idle); frame.append(svg); return frame;
        }
        const image = node('img'); image.src = mascotBaseURL + (pose === 'launcher' ? 'engenie-look-up.png' : 'engenie-genie.png');
        image.alt = ''; image.width = 40; image.height = 40; image.decoding = 'async';
        frame.append(image); return frame;
    }
    function getCSRF() {
        const cookie = document.cookie.split('; ').find(value => value.startsWith('csrftoken='));
        return cookie ? cookie.slice(10) : document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
    }
    function say(message) { const live = byId('aiChatLive'); if (live && live.textContent !== message) live.textContent = message; }
    function scrollLatest(force) { const box = byId('aiChatMessages'); if (box && (force || follow)) box.scrollTop = box.scrollHeight; }
    function modalMode() { return expanded || window.matchMedia('(max-width:768px)').matches; }
    function revealPanel(panel, open) {
        const version = ++motionVersion;
        const current = panel.hidden ? null : {opacity:getComputedStyle(panel).opacity, transform:getComputedStyle(panel).transform};
        panelMotion?.cancel(); panelMotion = null;
        panel.hidden = false; panel.inert = !open; panel.setAttribute('aria-hidden', String(!open));
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches || typeof panel.animate !== 'function') {
            panel.hidden = !open; return;
        }
        const rest = {opacity:1, transform:'none'}, fold = {opacity:0, transform:'translateY(18px) scale(.965)'};
        const motion = panel.animate([current || (open ? fold : rest), open ? rest : fold],
            {duration:open ? 320 : 180, easing:open ? 'cubic-bezier(.2,.85,.25,1)' : 'cubic-bezier(.4,0,1,1)', fill:'both'});
        panelMotion = motion;
        motion.finished.then(() => {
            if (version !== motionVersion) return;
            panel.hidden = !panelOpen; panelMotion = null; motion.cancel();
        }).catch(() => {});
    }
    function setOpen(open, {immediate=false,focus=true}={}) {
        const panel=byId('aiChatPanel');if(!panel)return;
        open=!!open&&workspaceAvailable;
        const changed=panelOpen!==open;panelOpen=open;
        if(immediate||!changed){
            motionVersion++;panelMotion?.cancel();panelMotion=null;
            panel.hidden=!open;panel.inert=!open;panel.setAttribute('aria-hidden',String(!open));
        }else revealPanel(panel,open);
        if(changed&&open)window.fosGenieArrival?.replay(panel);
        const launcher=byId('aiChatLauncher'),backdrop=byId('aiChatBackdrop');
        if(launcher){launcher.hidden=open||!workspaceAvailable;launcher.setAttribute('aria-expanded',String(open));}
        if(backdrop)backdrop.hidden=!open||!modalMode();
        document.body.classList.toggle('ai-chat-modal-open',open&&modalMode());
        panel.setAttribute('aria-modal',String(open&&modalMode()));
        if(open){loadHistory();activeRun?.view.refresh();if(focus)(modalMode()?byId('aiChatClose'):byId('aiChatInput'))?.focus();}
        else if(focus&&workspaceAvailable)launcher?.focus();
    }
    function toggle() { setOpen(!panelOpen); }
    function quotesAllowed() {
        const workspace = byId('dashboardWorkspace');
        const permission = workspace?.dataset.quotesEnabled;
        return workspaceAvailable && workspace?.dataset.business !== 'pest-control' && (permission == null ? quotesDefault : permission === 'yes');
    }
    function syncQuoteAccess() {
        const allowed = quotesAllowed();
        window.EnGenieQuotes?.setEnabled(allowed);
        responseViews.forEach(view => view.refresh());
        sendingState();
    }
    function quoteBusy() { return window.EnGenieQuotes?.isBlocking() === true; }
    function attachmentInfo(file) {
        if (!file || typeof file.id !== 'string') return null;
        const url = core.safeLink(file.url, window.location.origin);
        const safe = url && url.origin === window.location.origin && /^\/api\/ai\/attachments\/u\d+-[0-9a-f]{8,32}\/[0-9a-f-]{32,36}\/?$/i.test(url.pathname);
        return {id:file.id, name:String(file.name || '附件').slice(0,240), size:Number(file.size) || 0,
            kind:String(file.kind || 'document'), mime:String(file.mime || ''), url:safe ? url.href : ''};
    }
    function attachmentLink(file, className = 'ai-sent-attachment') {
        const item = node(file.url ? 'a' : 'span', className);
        if (file.url) { item.href = file.url; item.download = file.name; item.target = '_blank'; item.rel = 'noopener noreferrer'; }
        const glyph = node('span','ai-attachment-glyph'); glyph.innerHTML = icon('file');
        const text = node('span','ai-attachment-info'); text.append(node('strong','',file.name),node('small','',core.formatBytes(file.size)));
        item.append(glyph,text); return item;
    }
    function attachmentsBlocked() { return pendingAttachments.some(item => item.status !== 'ready'); }
    function clearAttachments() {
        attachmentGeneration++;
        pendingAttachments.forEach(item => item.controller?.abort()); pendingAttachments = [];
        const message = byId('aiChatAttachmentMessage'); if (message) { message.textContent = ''; message.hidden = true; }
        renderPendingAttachments();
    }
    function pauseUploads() {
        attachmentGeneration++;
        pendingAttachments.forEach(item => {
            item.controller?.abort();
            if (item.status === 'uploading') item.status = 'queued';
        });
        renderPendingAttachments();
    }
    function renderPendingAttachments() {
        const host = byId('aiChatAttachments'); if (!host) return;
        host.replaceChildren(); host.hidden = !pendingAttachments.length;
        for (const item of pendingAttachments) {
            const chip = node('div','ai-pending-attachment'); chip.dataset.status = item.status;
            const glyph = node('span','ai-attachment-glyph');
            glyph.innerHTML = item.status === 'uploading' || item.status === 'queued' ? '<span class="ai-spin-ring"></span>' : icon(item.status === 'ready' ? 'check' : 'alert');
            const info = node('div','ai-attachment-info');
            const name = node(item.attachment?.url ? 'a' : 'strong','ai-pending-file-name',item.attachment?.name || item.file.name);
            if (item.attachment?.url) { name.href = item.attachment.url; name.download = item.attachment.name; name.target = '_blank'; name.rel = 'noopener noreferrer'; }
            const labels = {queued:workspaceAvailable ? '等待上传' : '等待返回对话后上传',uploading:'正在上传…',ready:'已上传',error:item.error || '上传失败'};
            info.append(name,node('small','',core.formatBytes(item.attachment?.size ?? item.file.size) + ' · ' + labels[item.status]));
            const actions = node('div','ai-attachment-actions');
            if (item.status === 'error') {
                const retry = node('button','ai-attachment-retry','重试'); retry.type = 'button'; retry.disabled = !workspaceAvailable || !!activeRun || restoringHistory;
                retry.onclick = () => { item.status = 'queued'; item.error = ''; renderPendingAttachments(); uploadAttachments(); }; actions.append(retry);
            }
            const remove = node('button','ai-attachment-remove'); remove.type = 'button'; remove.innerHTML = icon('close'); remove.setAttribute('aria-label','移除附件：' + (item.attachment?.name || item.file.name));
            remove.onclick = () => { item.controller?.abort(); pendingAttachments = pendingAttachments.filter(other => other !== item); renderPendingAttachments(); };
            actions.append(remove); chip.append(glyph,info,actions); host.append(chip);
        }
        sendingState();
    }
    function addAttachments(files) {
        if (!workspaceAvailable || activeRun || restoringHistory) { say('请等待当前回复或对话加载完成，再添加附件。'); return; }
        if (historyDeadline !== null && performance.now() >= historyDeadline) {
            if (!newConversation()) return;
            loadHistory();
        }
        const errors = [];
        for (const file of files) {
            if (pendingAttachments.length >= attachmentLimit) { errors.push('每条消息最多添加 5 个附件。'); break; }
            if (!/\.(txt|md|log|json|csv|xlsx|docx|pdf|png|jpe?g|webp)$/i.test(file.name)) { errors.push(file.name + '：暂不支持此格式。'); continue; }
            if (file.size > attachmentMaxSize) { errors.push(file.name + '：单个附件不能超过 10 MB。'); continue; }
            if (!file.size) { errors.push(file.name + '：文件为空。'); continue; }
            pendingAttachments.push({localId:++attachmentSequence, file, status:'queued', attachment:null, error:'', controller:null});
        }
        const message = byId('aiChatAttachmentMessage');
        if (message) { message.textContent = [...new Set(errors)].join(' '); message.hidden = !errors.length; }
        if (errors.length) say(errors.join(' '));
        renderPendingAttachments(); uploadAttachments();
    }
    async function uploadAttachments() {
        const generation = attachmentGeneration;
        if (!workspaceAvailable || activeRun || restoringHistory || uploadWorkerGeneration === generation) return;
        uploadWorkerGeneration = generation;
        try {
            while (generation === attachmentGeneration && workspaceAvailable && !activeRun && !restoringHistory) {
                const item = pendingAttachments.find(value => value.status === 'queued'); if (!item) break;
                item.status = 'uploading'; item.controller = new AbortController(); renderPendingAttachments();
                const body = new FormData(), requestedThread = threadId;
                body.append('files', item.file); if (requestedThread) body.append('thread_id', requestedThread);
                try {
                    const response = await fetch('/api/ai/attachments', {method:'POST', credentials:'same-origin', signal:item.controller.signal,
                        headers:{'X-CSRFToken':getCSRF()}, body});
                    let data;
                    try { data = await response.json(); }
                    catch (_) { throw new Error(response.status === 413 ? '附件超过服务器允许的大小，请选择较小的文件。' : '未收到有效上传结果，请检查登录或网络状态后重试。'); }
                    if (generation !== attachmentGeneration || !pendingAttachments.includes(item)) continue;
                    if (!response.ok || !data.success) throw new Error(data.error || data.message || '上传失败，请重试。');
                    if (!/^u\d+-[0-9a-f]{8,32}$/.test(data.thread_id || '') || requestedThread && data.thread_id !== requestedThread) throw new Error('附件所属对话已变化，请重新添加。');
                    const attachment = attachmentInfo(data.attachments?.[0]);
                    if (!attachment) throw new Error('未收到有效附件信息，请重试。');
                    threadId = data.thread_id; item.attachment = attachment; item.status = 'ready';
                    setHistoryPolicy(data); say(attachment.name + ' 已上传');
                } catch (error) {
                    if (generation !== attachmentGeneration || !pendingAttachments.includes(item)) continue;
                    item.status = 'error'; item.error = error.name === 'AbortError' ? '上传已取消，可重试。' : error.message || '网络连接中断，请重试。';
                    say(item.file.name + '：' + item.error);
                } finally {
                    if (generation === attachmentGeneration) { item.controller = null; renderPendingAttachments(); }
                }
            }
        } finally {
            if (uploadWorkerGeneration === generation) uploadWorkerGeneration = null;
            if (generation === attachmentGeneration) { sendingState(); loadHistory(); }
        }
    }
    function restageAttachments(files, ownerThread) {
        if (!ownerThread || ownerThread !== threadId) { say('原附件属于另一个对话，请重新添加附件。'); return; }
        for (const file of files) {
            if (pendingAttachments.length >= attachmentLimit) break;
            if (!pendingAttachments.some(item => item.attachment?.id === file.id)) pendingAttachments.push({localId:++attachmentSequence,file:null,status:'ready',attachment:file,error:'',controller:null});
        }
        renderPendingAttachments();
    }
    function welcome({preserveQuotes = false} = {}) {
        const quotes = window.EnGenieQuotes?.retainPending(preserveQuotes) || [];
        const box = byId('aiChatMessages'); box.replaceChildren();
        responseViews.forEach((view, article) => { if (!quotes.includes(article)) responseViews.delete(article); });
        const empty = node('div','ai-welcome'); empty.id = 'aiChatWelcome';
        const art = node('div','ai-welcome-icon'); art.append(mascot('welcome'));
        const title = node('h3','', 'EnGenie');
        title.append(node('span','ai-welcome-tagline', ' — Your Intelligent Irrigation Companion'));
        empty.append(art, title, node('p','', '你好，我是 EnGenie。今天需要什么帮助？'));
        const prompts = node('div','ai-prompts');
        ['汇总本周的维修记录','查看最近的灌溉与用水情况','分析 PM 待办并生成报表'].forEach(text => {
            const b = node('button','ai-prompt',text); b.type = 'button';
            b.onclick = () => { byId('aiChatInput').value = text; resizeInput(); byId('aiChatInput').focus(); }; prompts.append(b);
        });
        empty.append(prompts); box.append(empty,...quotes); if (quotes.length) empty.remove();
    }
    async function copyText(text, button) {
        try {
            await navigator.clipboard.writeText(text);
            const originalLabel = button.getAttribute('aria-label');
            const original = [...button.childNodes]; button.replaceChildren();
            if (button.classList.contains('ai-code-copy')) button.textContent = '已复制'; else button.innerHTML = icon('check');
            button.setAttribute('aria-label','已复制'); say('已复制');
            setTimeout(() => { if (button.isConnected) { button.replaceChildren(...original); if (originalLabel) button.setAttribute('aria-label',originalLabel); else button.removeAttribute('aria-label'); } },1500);
        }
        catch (_) { say('复制未成功，请选择文本复制。'); }
    }
    function renderMarkdown(target, text, files, final) {
        if (!window.marked || !window.DOMPurify) { target.textContent = text; target.classList.add('ai-plain'); return; }
        const fragment = window.DOMPurify.sanitize(window.marked.parse(text, {gfm:true, breaks:false}), {
            ALLOWED_TAGS:['p','h1','h2','h3','h4','strong','em','del','blockquote','ul','ol','li','a','code','pre','br','hr','table','thead','tbody','tr','th','td','img'],
            ALLOWED_ATTR:['href','title','alt','src','align','colspan','rowspan'], RETURN_DOM_FRAGMENT:true
        });
        fragment.querySelectorAll('a').forEach(link => {
            const url = core.safeLink(link.getAttribute('href'), window.location.origin);
            if (!url) { link.removeAttribute('href'); return; }
            link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer';
        });
        fragment.querySelectorAll('img').forEach(image => {
            const file = core.artifactInfo({url:image.getAttribute('src')}, window.location.origin);
            if (!file || file.kind !== 'image' || files.some(item => core.artifactInfo(item,window.location.origin)?.url === file.url)) { image.remove(); return; }
            image.src = file.url; image.loading = 'lazy'; image.decoding = 'async';
        });
        fragment.querySelectorAll('table').forEach(table => {
            const wrap = node('div','ai-table-scroll'); wrap.tabIndex = 0; wrap.setAttribute('role','region'); wrap.setAttribute('aria-label','数据表，可左右滚动');
            table.replaceWith(wrap); wrap.append(table);
        });
        if (final) fragment.querySelectorAll('pre').forEach(pre => {
            const code = pre.querySelector('code'); if (!code) return;
            const b = node('button','ai-code-copy','复制'); b.type = 'button'; b.onclick = () => copyText(code.textContent,b); pre.prepend(b);
        });
        target.replaceChildren(fragment);
    }
    const duration = (start,end) => ((end-start)/1000).toFixed(1) + ' 秒';
    function responseView(requestText, attachments = [], ownerThread = threadId, restore = false) {
        byId('aiChatWelcome')?.remove();
        const box = byId('aiChatMessages');
        const user = node('article','ai-msg ai-msg-user'), userContent = node('div','ai-user-content');
        if (requestText) userContent.append(node('div','ai-user-text',requestText));
        if (attachments.length) {
            const files = node('div','ai-sent-attachments'); files.setAttribute('aria-label','本条消息的附件');
            attachments.forEach(file => files.append(attachmentLink(file))); userContent.append(files);
        }
        user.append(userContent); box.append(user);
        const turn = core.createTurn();
        const article = node('article','ai-msg ai-msg-assistant'); article.setAttribute('aria-label','EnGenie 回复');
        const heading = node('div','ai-turn-head'), avatar = node('span','ai-turn-avatar'); avatar.append(mascot());
        const status = node('span','ai-turn-status'), copy = node('button','ai-icon-button ai-copy-response');
        copy.type = 'button'; copy.title = '复制回复'; copy.setAttribute('aria-label','复制回复'); copy.innerHTML = icon('copy'); copy.hidden = true;
        copy.onclick = () => copyText(turn.text,copy); heading.append(avatar,status,copy);
        const work = node('details','ai-work'); work.hidden = true;
        const summary = node('summary','ai-work-summary'), toolList = node('div','ai-tool-list'); work.append(summary,toolList);
        summary.onclick = () => { work.dataset.keepOpen = String(!work.open); };
        const content = node('div','ai-answer'), artifacts = node('div','ai-artifacts'), quotes = node('div','ai-quote-drafts'), note = node('div','ai-response-note'); note.hidden = true;
        article.append(heading,work,content,artifacts,quotes,note); box.append(article);
        const rows = new Map(), cards = new Set(), quoteCards = new Set(); let frame = null, initialTools = true;
        function renderQuotes() {
            const drafts = turn.quoteDrafts || [];
            if (!drafts.length) return;
            if (!quotesAllowed() || !window.EnGenieQuotes) {
                if (!quotes.querySelector('.ai-quote-unavailable')) quotes.prepend(node('p','ai-quote-unavailable','当前业务视图不支持库存报价确认，请切换至有权限的灌溉业务后处理。'));
                return;
            }
            quotes.querySelector('.ai-quote-unavailable')?.remove();
            for (const draft of drafts) {
                if (!draft?.submission_key || quoteCards.has(draft.submission_key)) continue;
                quoteCards.add(draft.submission_key);
                window.EnGenieQuotes.mount({host:quotes,csrf:getCSRF,draft,restore,onChange:()=>scrollLatest(false),onStatus:say,onBusy:sendingState});
            }
        }
        function renderTools() {
            if (!turn.tools.length) return;
            work.hidden = false;
            if (initialTools) { work.open = true; initialTools = false; }
            const completed = turn.tools.filter(tool => tool.status === 'done').length;
            summary.textContent = turn.ended !== null ? '操作记录 · ' + turn.tools.length + ' 项' : '正在处理 · ' + completed + '/' + turn.tools.length + ' 项已完成';
            turn.tools.forEach(tool => {
                let row = rows.get(tool.id);
                if (!row) {
                    row = node('details','ai-tool'); row.dataset.callId = tool.id;
                    const line = node('summary','ai-tool-line'); line.append(node('span','ai-tool-state'), node('span','ai-tool-name'), node('span','ai-tool-duration'));
                    row.append(line,node('pre','ai-tool-detail')); toolList.append(row); rows.set(tool.id,row);
                }
                row.dataset.status = tool.status;
                row.querySelector('.ai-tool-name').textContent = core.toolLabel(tool.name);
                row.querySelector('.ai-tool-state').innerHTML = tool.status === 'running' ? '<span class="ai-spin-ring"></span>' : icon(tool.status === 'done' ? 'check' : tool.status === 'error' ? 'alert' : 'minus');
                row.querySelector('.ai-tool-duration').textContent = tool.ended === null ? '进行中' : (tool.status === 'error' ? '失败 · ' : tool.status === 'interrupted' ? '未收到结果 · ' : '') + duration(tool.started,tool.ended);
                row.querySelector('.ai-tool-detail').textContent = (Object.keys(tool.args || {}).length ? JSON.stringify(tool.args,null,2) + '\n\n' : '') + (tool.output || '等待返回结果…').slice(0,2400);
            });
            if (turn.ended !== null && work.dataset.keepOpen !== 'true') work.open = false;
        }
        function renderFiles() {
            turn.files.forEach(file => {
                const info = core.artifactInfo(file,window.location.origin); if (!info || cards.has(info.url)) return; cards.add(info.url);
                const item = node('section','ai-artifact'); item.dataset.kind = info.kind;
                if (info.kind === 'image') {
                    const preview = node('a','ai-chart-preview'); preview.href = info.url; preview.target = '_blank'; preview.rel = 'noopener'; preview.setAttribute('aria-label','查看原图：' + info.name);
                    const image = node('img'); image.src = info.url; image.alt = info.name; image.loading = 'lazy'; image.decoding = 'async';
                    image.onerror = () => { preview.replaceChildren(node('span','ai-preview-error','预览暂不可用，可下载原文件')); }; preview.append(image); item.append(preview);
                }
                const link = node('a','ai-file-card'); link.href = info.url; link.download = info.name;
                const symbol = node('span','ai-file-symbol'); symbol.innerHTML = icon(info.kind === 'spreadsheet' || info.kind === 'image' ? 'chart' : 'file');
                const body = node('span','ai-file-info'); body.append(node('strong','ai-file-name',info.name), node('small','ai-file-meta',[info.type,info.size].filter(Boolean).join(' · ')));
                const download = node('span','ai-file-download'); download.innerHTML = icon('download'); link.append(symbol,body,download); item.append(link); artifacts.append(item);
            });
        }
        function render() {
            frame = null;
            if (!panelOpen && turn.ended === null) return;
            const previousScroll = box.scrollTop;
            const phases = {preparing:'正在准备回复',thinking:'正在整理结果',writing:'正在回复',tool:'正在使用工具',done:'已完成',error:'回复未完成',stopped:'已请求停止'};
            const label = phases[turn.phase] || '正在处理'; article.dataset.phase = turn.phase;
            status.textContent = label + (turn.ended !== null ? ' · ' + duration(turn.started,turn.ended) : ''); say(label); copy.hidden = !turn.text;
            if (turn.text) renderMarkdown(content,turn.text,turn.files,turn.ended !== null);
            renderTools(); renderFiles(); renderQuotes();
            if (turn.phase === 'error' || turn.phase === 'stopped') {
                note.hidden = false; note.replaceChildren(node('p','',turn.error || '已请求停止任务，后台正在收尾。请稍候再发起新任务。'));
                const edit = node('button','ai-edit-request','重新编辑请求'); edit.type = 'button'; edit.onclick = () => {
                    byId('aiChatInput').value = requestText;
                    if (attachments.length) restageAttachments(attachments,ownerThread);
                    resizeInput(); byId('aiChatInput').focus();
                }; note.append(edit);
            }
            if (follow) scrollLatest(false); else box.scrollTop = previousScroll;
        }
        render(); scrollLatest(true);
        const view = {turn, refresh:render, event(event) { core.applyEvent(turn,event); if (!frame) frame = requestAnimationFrame(render); },
            finish(phase,message) { if (frame) cancelAnimationFrame(frame); frame = null; core.finishTurn(turn,phase,message); render(); }};
        responseViews.set(article,view); return view;
    }
    function resizeInput() {
        const input = byId('aiChatInput'); if (!input) return;
        input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight + 2,144) + 'px';
        const latest = byId('aiChatLatest'), composer = document.querySelector('#aiChatPanel .ai-composer');
        if (latest && composer) latest.style.bottom = (composer.offsetHeight + 12) + 'px';
        const button = byId('aiChatSend');
        if (button) button.disabled = !activeRun && (!workspaceAvailable || restoringHistory || attachmentsBlocked() || !input.value.trim() && !pendingAttachments.length);
    }
    function sendingState() {
        const button = byId('aiChatSend'); if (!button) return;
        button.innerHTML = icon(activeRun ? 'stop' : 'send'); button.title = activeRun ? '停止任务' : '发送'; button.setAttribute('aria-label',button.title); button.dataset.sending = String(!!activeRun); resizeInput();
        const busy = quoteBusy();
        if(byId('aiChatHistory'))byId('aiChatHistory').disabled=!!activeRun || busy || restoringHistory;
        if(byId('aiChatNew'))byId('aiChatNew').disabled=busy;
        const add = byId('aiChatAddAttachment'); if (add) add.disabled = !workspaceAvailable || !!activeRun || restoringHistory || pendingAttachments.length >= attachmentLimit;
    }
    function stop() { if (activeRun) {
        if (threadId) fetch('/api/ai/cancel',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':getCSRF()},body:JSON.stringify({thread_id:threadId})}).catch(()=>{});
        activeRun.controller.abort(); activeRun.view.finish('stopped');
    } }
    async function loadHistory() {
        const select=byId('aiChatHistory');if(!select)return;
        try{const data=await fetch('/api/ai/conversations',{credentials:'same-origin',cache:'no-store'}).then(r=>r.ok?r.json():{});
            if (!data.day) return;
            if (historyDay && data.day < historyDay) return;
            if (historyDay && historyDay !== data.day) {
                if (quoteBusy()) { clearTimeout(historyTimer); historyTimer = setTimeout(loadHistory,60000); return; }
                newConversation(); say('已切换到新的一天，聊天记录和附件仅保留当天。');
            }
            setHistoryPolicy(data);
            select.replaceChildren(new Option('当天对话（上海时间）',''));
            for(const item of data.conversations||[])select.add(new Option(item.title||'未命名对话',item.id));
            if(threadId)select.value=threadId;
        }catch(_){}
    }
    function setHistoryPolicy(data) {
        const delay = core.retentionDelay(data);
        if (delay === null) return;
        historyDay = data.day;
        historyDeadline = performance.now() + delay;
        clearTimeout(historyTimer);
        historyTimer = setTimeout(() => {
            if (quoteBusy()) { historyTimer = setTimeout(loadHistory,60000); return; }
            newConversation(); historyDay = null;
            say('已切换到新的一天，聊天记录和附件仅保留当天。');
            loadHistory();
        }, Math.min(delay + 100, 2147483647));
    }
    async function restoreHistory(id) {
        if(!id||activeRun)return;
        if (quoteBusy()) { byId('aiChatHistory').value = threadId || ''; say('当前报价还在处理中，请先完成确认再切换对话。'); return; }
        const version = ++historyRestoreVersion; pauseUploads(); restoringHistory = true; sendingState();
        try{const response=await fetch('/api/ai/conversations?thread_id='+encodeURIComponent(id),{credentials:'same-origin',cache:'no-store'});
            if (version !== historyRestoreVersion) return;
            if(response.status===404) { newConversation(); loadHistory(); throw new Error('会话已过期，历史记录仅保留当天。'); }
            if(!response.ok)throw new Error('会话暂时无法恢复');
            const data=await response.json();
            if (version !== historyRestoreVersion) return;
            if (quoteBusy()) { byId('aiChatHistory').value = threadId || ''; say('当前报价还在处理中，请先完成确认再切换对话。'); return; }
            clearAttachments(); welcome();threadId=id;setHistoryPolicy(data);byId('aiChatSnapshot').textContent='历史回复 · 再次发送时更新数据快照';
            for(const turn of data.turns||[]){
                const files = (turn.attachments || []).map(attachmentInfo).filter(Boolean);
                const view=responseView(turn.question,files,id,true);view.event({event:'token',text:turn.answer||''});
                for(const file of turn.files||[])view.event({event:'file',...file});
                for(const draft of turn.quote_drafts||[])view.event({event:'quote_draft',draft});
                view.finish('done');
            }
            resetFollow();scrollLatest(true);
        }catch(error){if (version === historyRestoreVersion) { byId('aiChatHistory').value = threadId || ''; say(error.message); }}
        finally { if (version === historyRestoreVersion) { restoringHistory = false; sendingState(); uploadAttachments(); } }
    }
    function resetFollow() { follow = true; byId('aiChatLatest').hidden = true; }
    function newConversation() {
        if (quoteBusy()) { say('当前报价还在处理中，请先完成确认再新建对话。'); return false; }
        historyRestoreVersion++; restoringHistory = false; clearAttachments();
        stop(); sequence++; activeRun = null; threadId = null; sendingState(); welcome(); resetFollow();byId('aiChatHistory').value='';byId('aiChatSnapshot').textContent=''; say('已开启新对话'); return true;
    }
    async function send() {
        const input = byId('aiChatInput'); if (!input || activeRun || restoringHistory || !workspaceAvailable) return;
        if (historyDeadline !== null && performance.now() >= historyDeadline) {
            if (pendingAttachments.length) { newConversation(); loadHistory(); say('对话附件已跨天过期，请重新添加后发送。'); return; }
            newConversation(); loadHistory();
        }
        if (attachmentsBlocked()) { say('请等待附件上传完成；失败的附件请重试或移除。'); return; }
        const attachments = pendingAttachments.map(item => item.attachment).filter(Boolean);
        const text = input.value.trim() || (attachments.length ? '请查看这些附件。' : ''); if (!text) return;
        input.value = ''; pendingAttachments = []; renderPendingAttachments(); resetFollow();
        const attachmentMessage = byId('aiChatAttachmentMessage'); if (attachmentMessage) { attachmentMessage.hidden = true; attachmentMessage.textContent = ''; }
        const run = {id:++sequence, controller:new AbortController(), view:responseView(text,attachments,threadId)}; activeRun = run; sendingState(); let completed = false;
        try {
            const response = await fetch('/api/ai/chat',{method:'POST',credentials:'same-origin',signal:run.controller.signal,headers:{'Content-Type':'application/json','X-CSRFToken':getCSRF()},body:JSON.stringify({message:text,thread_id:threadId,attachment_ids:attachments.map(file=>file.id)})});
            if (!response.ok) {
                let message = '请求失败 (HTTP ' + response.status + ')'; try { const data = await response.json(); if (data.error) message = String(data.error); } catch (_) {} throw new Error(message);
            }
            if (!response.body || !response.headers.get('Content-Type')?.includes('text/event-stream')) throw new Error('未收到有效回复，请检查登录状态后重试。');
            const reader = response.body.getReader(), decoder = new TextDecoder();
            const parser = core.createParser(event => {
                if (sequence !== run.id || run.controller.signal.aborted) return;
                if (event.event === 'thread') {
                    if (event.reset) { run.view.finish('stopped'); welcome({preserveQuotes:true}); run.view=responseView(text,attachments,event.thread_id); }
                    if (/^u\d+-[0-9a-f]{8,32}$/.test(event.thread_id || '')) threadId = event.thread_id;
                    setHistoryPolicy(event); return;
                }
                if (event.event === 'snapshot') { const hint=byId('aiChatSnapshot');if(hint)hint.textContent='数据快照更新于 '+new Date(event.at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'});return; }
                if (event.event === 'done') completed = true; run.view.event(event);
            });
            while (true) {
                const chunk = await reader.read();
                if (sequence !== run.id || run.controller.signal.aborted) { await reader.cancel(); break; }
                if (chunk.done) { parser.finish(decoder.decode()); break; }
                parser.push(decoder.decode(chunk.value,{stream:true}));
            }
            if (!run.controller.signal.aborted && sequence === run.id) run.view.finish(completed ? 'done' : 'error', completed ? '' : '连接已结束，回复可能尚未完成。');
        } catch (error) {
            if (sequence === run.id && !run.controller.signal.aborted) { run.view.finish('error',error.message || '网络连接中断，请检查后重试。'); run.controller.abort(); }
        } finally { if (activeRun === run) { activeRun = null; sendingState();loadHistory(); } }
    }
    function mount(preview) {
        if (byId('aiChatPanel')) return;
        const launcher = node('button','ai-launcher-btn'); launcher.id = 'aiChatLauncher'; launcher.type = 'button'; launcher.title = 'EnGenie · 智能灌溉伙伴'; launcher.setAttribute('aria-label','打开 EnGenie 智能灌溉助手'); launcher.setAttribute('aria-controls','aiChatPanel'); launcher.setAttribute('aria-expanded','false'); launcher.append(mascot('launcher')); launcher.onclick = toggle;
        const media = window.matchMedia('(max-width:768px)');
        function placeLauncher() {
            const controls = byId('mobileBtnCluster'); const parent = controls && media.matches ? controls : document.body; if (launcher.parentElement !== parent) parent.append(launcher);
            if (panelOpen) { byId('aiChatBackdrop').hidden = !modalMode(); byId('aiChatPanel').setAttribute('aria-modal',String(modalMode())); document.body.classList.toggle('ai-chat-modal-open',modalMode()); }
        }
        const backdrop = node('div','ai-chat-backdrop'); backdrop.id = 'aiChatBackdrop'; backdrop.hidden = true; backdrop.onclick = () => setOpen(false);
        const panel = node('section','ai-chat-panel'); panel.id = 'aiChatPanel'; panel.hidden = true; panel.setAttribute('role','dialog'); panel.setAttribute('aria-labelledby','aiChatTitle'); panel.setAttribute('aria-modal','false');
        panel.innerHTML = '<header class="ai-chat-header"><div class="ai-chat-heading"><span class="ai-header-icon"></span><div><h2 id="aiChatTitle">EnGenie</h2><p>智能灌溉伙伴</p></div></div><div class="ai-header-actions"><button type="button" id="aiChatNew" class="ai-icon-button" title="新建对话" aria-label="新建对话">' + icon('plus') + '</button><button type="button" id="aiChatExpand" class="ai-icon-button" title="展开对话" aria-label="展开对话">' + icon('expand') + '</button><button type="button" id="aiChatClose" class="ai-icon-button" title="关闭" aria-label="关闭 EnGenie">' + icon('close') + '</button></div></header><div id="aiChatLive" class="pwa-sr-only" aria-live="polite" aria-atomic="true"></div><div id="aiChatMessages" class="ai-chat-messages" role="log" aria-live="off" aria-label="对话内容"></div><button type="button" id="aiChatLatest" class="ai-latest" hidden>' + icon('chevron-down') + ' 回到最新</button><div class="ai-composer"><label class="pwa-sr-only" for="aiChatInput">发送给 EnGenie</label><div class="ai-composer-box"><textarea id="aiChatInput" placeholder="向 EnGenie 提问…" rows="1"></textarea><button type="button" id="aiChatSend" aria-label="发送" disabled>' + icon('send') + '</button></div><p class="ai-composer-hint">Enter 发送 · Shift+Enter 换行</p></div>';
        panel.inert=true;panel.setAttribute('aria-hidden','true');
        panel.querySelector('.ai-header-icon').append(mascot());
        repositionLauncher=placeLauncher;workspaceAvailable=byId('dashboardWorkspace')?.dataset.ai!=='no';
        document.body.append(backdrop,panel); placeLauncher();launcher.hidden=!workspaceAvailable; if (media.addEventListener) media.addEventListener('change',placeLauncher); else media.addListener(placeLauncher);
        if (preview) byId('aiChatTitle').append(node('span','ai-preview-badge','演示'));
        function fitViewport() {
            const viewport = window.visualViewport;
            if (!viewport || viewport.scale !== 1) return;
            panel.style.setProperty('--ai-viewport-height', viewport.height + 'px');
            panel.style.setProperty('--ai-viewport-top', viewport.offsetTop + 'px');
        }
        const history=document.createElement('select');history.id='aiChatHistory';history.className='ai-chat-history';history.setAttribute('aria-label','当天对话（上海时间）');
        history.title='聊天记录和生成的附件仅保留上海时间当天，每日 00:00 过期';
        history.add(new Option('当天对话（上海时间）',''));history.onchange=()=>restoreHistory(history.value);
        panel.querySelector('.ai-chat-header').after(history);
        const snapshot=document.createElement('p');snapshot.id='aiChatSnapshot';snapshot.className='ai-composer-hint';panel.querySelector('.ai-composer').append(snapshot);
        const attachments = node('div','ai-pending-attachments'); attachments.id = 'aiChatAttachments'; attachments.hidden = true;
        attachments.setAttribute('aria-label','待发送附件');
        const attachmentMessage = node('p','ai-attachment-message'); attachmentMessage.id = 'aiChatAttachmentMessage'; attachmentMessage.hidden = true; attachmentMessage.setAttribute('role','status');
        const attach = node('button','ai-add-attachment'); attach.id = 'aiChatAddAttachment'; attach.type = 'button'; attach.innerHTML = icon('paperclip');
        attach.title = '添加附件 · 最多 5 个，每个不超过 10 MB'; attach.setAttribute('aria-label','添加附件');
        const fileInput = node('input'); fileInput.type = 'file'; fileInput.accept = attachmentAccept; fileInput.multiple = true; fileInput.hidden = true;
        fileInput.setAttribute('aria-label','选择附件'); attach.onclick = () => fileInput.click();
        fileInput.onchange = () => { const files = [...fileInput.files]; fileInput.value = ''; addAttachments(files); };
        const composer = panel.querySelector('.ai-composer'); composer.prepend(attachments,attachmentMessage);
        panel.querySelector('.ai-composer-box').prepend(attach,fileInput); syncQuoteAccess();
        const dropHint = node('div','ai-drop-hint','松开即可添加附件'); dropHint.setAttribute('aria-hidden','true'); panel.append(dropHint);
        let dragDepth = 0;
        const hasFiles = event => [...(event.dataTransfer?.types || [])].includes('Files');
        panel.addEventListener('dragenter', event => { if (!hasFiles(event)) return; event.preventDefault(); dragDepth++; panel.classList.add('is-dropping'); });
        panel.addEventListener('dragover', event => { if (!hasFiles(event)) return; event.preventDefault(); event.dataTransfer.dropEffect = 'copy'; });
        panel.addEventListener('dragleave', event => { if (!hasFiles(event)) return; if (--dragDepth <= 0) { dragDepth = 0; panel.classList.remove('is-dropping'); } });
        panel.addEventListener('drop', event => {
            if (!hasFiles(event)) return; event.preventDefault(); dragDepth = 0; panel.classList.remove('is-dropping'); addAttachments([...(event.dataTransfer?.files || [])]);
        });
        loadHistory();
        document.addEventListener('visibilitychange', () => { if (!document.hidden) loadHistory(); });
        fitViewport();
        window.visualViewport?.addEventListener('resize',fitViewport,{passive:true});
        window.visualViewport?.addEventListener('scroll',fitViewport,{passive:true});
        byId('aiChatClose').onclick = () => setOpen(false); byId('aiChatNew').onclick = newConversation;
        byId('aiChatExpand').onclick = () => { expanded = !expanded; panel.classList.toggle('is-expanded',expanded); byId('aiChatExpand').innerHTML = icon(expanded ? 'collapse' : 'expand'); byId('aiChatExpand').setAttribute('aria-label',expanded ? '收起对话' : '展开对话'); byId('aiChatExpand').title = expanded ? '收起对话' : '展开对话'; placeLauncher(); };
        byId('aiChatSend').onclick = () => activeRun ? stop() : send();
        const input = byId('aiChatInput'); input.addEventListener('input',resizeInput);
        input.addEventListener('paste', event => {
            const files = [...(event.clipboardData?.files || [])]; if (!files.length) return;
            if (!event.clipboardData.getData('text/plain')) event.preventDefault();
            addAttachments(files);
        });
        input.addEventListener('keydown',event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); send(); } });
        const box = byId('aiChatMessages'); box.addEventListener('scroll',() => { follow = box.scrollHeight-box.scrollTop-box.clientHeight < 80; byId('aiChatLatest').hidden = follow; },{passive:true});
        byId('aiChatLatest').onclick = () => { follow = true; scrollLatest(true); byId('aiChatLatest').hidden = true; };
        panel.addEventListener('keydown',event => {
            if (event.key === 'Escape') { event.preventDefault(); setOpen(false); }
            if (event.key !== 'Tab' || !modalMode()) return;
            const focusable = [...panel.querySelectorAll('button,a[href],input:not([type="file"]),textarea,select,summary,[tabindex="0"]')].filter(item => !item.matches(':disabled') && !item.closest('[inert]') && item.getClientRects().length);
            const first = focusable[0], last = focusable[focusable.length-1];
            if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
            else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
        });
        welcome();
    }
    function mountIfAvailable() {
        if (byId('aiChatPanel') || byId('dashboardWorkspace')?.dataset.ai !== 'yes') return;
        if (availabilityRequest) return availabilityRequest;
        const version = availabilityVersion;
        availabilityRequest = fetch('/api/ai/status',{credentials:'same-origin',cache:'no-store'})
            .then(response => response.ok ? response.json() : null)
            .then(data => {
                // A business switch may finish while this read is in flight.
                if (version === availabilityVersion && data?.available && byId('dashboardWorkspace')?.dataset.ai === 'yes') mount(data.preview === true);
            }).catch(() => {}).finally(() => {
                availabilityRequest = null;
                if (version !== availabilityVersion) mountIfAvailable();
            });
        return availabilityRequest;
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded',mountIfAvailable); else mountIfAvailable();
    window.addEventListener('pageshow',mountIfAvailable);
    window.AIChat = {open:()=>setOpen(true),toggle,close:()=>setOpen(false),
        beforeWorkspaceChange(){
            pauseUploads();
            window.EnGenieQuotes?.setEnabled(false);
            setOpen(false,{immediate:true,focus:false});
            const launcher=byId('aiChatLauncher');if(launcher&&launcher.parentElement!==document.body)document.body.append(launcher);
        },
        afterWorkspaceChange(){
            availabilityVersion += 1;
            workspaceAvailable=byId('dashboardWorkspace')?.dataset.ai==='yes';
            repositionLauncher();setOpen(false,{immediate:true,focus:false});syncQuoteAccess();
            renderPendingAttachments(); if (workspaceAvailable) uploadAttachments();
            if (workspaceAvailable) mountIfAvailable();
        }};
})();
