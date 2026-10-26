/* Accessible streaming assistant UI. Business actions remain server-side. */
(function () {
    'use strict';
    const core = window.AIChatCore;
    if (!core) return;
    let threadId = null, activeRun = null, sequence = 0, panelOpen = false, expanded = false, follow = true;
    let historyDay = null, historyTimer = null, historyDeadline = null;
    const byId = id => document.getElementById(id);
    const icon = name => window.uiIcon(name);
    const node = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
    function getCSRF() {
        const cookie = document.cookie.split('; ').find(value => value.startsWith('csrftoken='));
        return cookie ? cookie.slice(10) : document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
    }
    function say(message) { const live = byId('aiChatLive'); if (live && live.textContent !== message) live.textContent = message; }
    function scrollLatest(force) { const box = byId('aiChatMessages'); if (box && (force || follow)) box.scrollTop = box.scrollHeight; }
    function modalMode() { return expanded || window.matchMedia('(max-width:768px)').matches; }
    function setOpen(open) {
        const panel = byId('aiChatPanel'); if (!panel) return;
        panelOpen = open; panel.hidden = !open;
        byId('aiChatLauncher').hidden = open;
        byId('aiChatLauncher').setAttribute('aria-expanded', String(open));
        byId('aiChatBackdrop').hidden = !open || !modalMode();
        document.body.classList.toggle('ai-chat-modal-open', open && modalMode());
        panel.setAttribute('aria-modal', String(open && modalMode()));
        if (open) { loadHistory(); activeRun?.view.refresh(); (modalMode() ? byId('aiChatClose') : byId('aiChatInput')).focus(); }
        else byId('aiChatLauncher').focus();
    }
    function toggle() { setOpen(!panelOpen); }
    function welcome() {
        const box = byId('aiChatMessages'); box.replaceChildren();
        const empty = node('div','ai-welcome'); empty.id = 'aiChatWelcome';
        const art = node('div','ai-welcome-icon'); art.innerHTML = icon('ai');
        empty.append(art, node('h3','', '有什么可以帮你？'), node('p','', '查询灌溉数据，梳理维修记录，生成图表与报表。'));
        const prompts = node('div','ai-prompts');
        ['汇总本周的维修记录','查看最近的灌溉与用水情况','分析 PM 待办并生成报表'].forEach(text => {
            const b = node('button','ai-prompt',text); b.type = 'button';
            b.onclick = () => { byId('aiChatInput').value = text; resizeInput(); byId('aiChatInput').focus(); }; prompts.append(b);
        });
        empty.append(prompts); box.append(empty);
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
    function responseView(requestText) {
        byId('aiChatWelcome')?.remove();
        const box = byId('aiChatMessages');
        const user = node('article','ai-msg ai-msg-user'); user.append(node('div','ai-user-text',requestText)); box.append(user);
        const turn = core.createTurn();
        const article = node('article','ai-msg ai-msg-assistant'); article.setAttribute('aria-label','助手回复');
        const heading = node('div','ai-turn-head'), avatar = node('span','ai-turn-avatar'); avatar.innerHTML = icon('ai');
        const status = node('span','ai-turn-status'), copy = node('button','ai-icon-button ai-copy-response');
        copy.type = 'button'; copy.title = '复制回复'; copy.setAttribute('aria-label','复制回复'); copy.innerHTML = icon('copy'); copy.hidden = true;
        copy.onclick = () => copyText(turn.text,copy); heading.append(avatar,status,copy);
        const work = node('details','ai-work'); work.hidden = true;
        const summary = node('summary','ai-work-summary'), toolList = node('div','ai-tool-list'); work.append(summary,toolList);
        summary.onclick = () => { work.dataset.keepOpen = String(!work.open); };
        const content = node('div','ai-answer'), artifacts = node('div','ai-artifacts'), note = node('div','ai-response-note'); note.hidden = true;
        article.append(heading,work,content,artifacts,note); box.append(article);
        const rows = new Map(), cards = new Set(); let frame = null, initialTools = true;
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
            renderTools(); renderFiles();
            if (turn.phase === 'error' || turn.phase === 'stopped') {
                note.hidden = false; note.replaceChildren(node('p','',turn.error || '已请求停止任务，后台正在收尾。请稍候再发起新任务。'));
                const edit = node('button','ai-edit-request','重新编辑请求'); edit.type = 'button'; edit.onclick = () => { byId('aiChatInput').value = requestText; resizeInput(); byId('aiChatInput').focus(); }; note.append(edit);
            }
            if (follow) scrollLatest(false); else box.scrollTop = previousScroll;
        }
        render(); scrollLatest(true);
        return {turn, refresh:render, event(event) { core.applyEvent(turn,event); if (!frame) frame = requestAnimationFrame(render); },
            finish(phase,message) { if (frame) cancelAnimationFrame(frame); frame = null; core.finishTurn(turn,phase,message); render(); }};
    }
    function resizeInput() {
        const input = byId('aiChatInput'); if (!input) return;
        input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight + 2,144) + 'px';
        const latest = byId('aiChatLatest'), composer = document.querySelector('#aiChatPanel .ai-composer');
        if (latest && composer) latest.style.bottom = (composer.offsetHeight + 12) + 'px';
        const button = byId('aiChatSend'); if (button) button.disabled = !activeRun && !input.value.trim();
    }
    function sendingState() {
        const button = byId('aiChatSend'); if (!button) return;
        button.innerHTML = icon(activeRun ? 'stop' : 'send'); button.title = activeRun ? '停止任务' : '发送'; button.setAttribute('aria-label',button.title); button.dataset.sending = String(!!activeRun); resizeInput();
        if(byId('aiChatHistory'))byId('aiChatHistory').disabled=!!activeRun;
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
            if (historyDay && historyDay !== data.day) { newConversation(); say('已切换到新的一天，聊天记录和附件仅保留当天。'); }
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
            newConversation(); historyDay = null;
            say('已切换到新的一天，聊天记录和附件仅保留当天。');
            loadHistory();
        }, Math.min(delay + 100, 2147483647));
    }
    async function restoreHistory(id) {
        if(!id||activeRun)return;
        try{const response=await fetch('/api/ai/conversations?thread_id='+encodeURIComponent(id),{credentials:'same-origin',cache:'no-store'});
            if(response.status===404) { newConversation(); loadHistory(); throw new Error('会话已过期，历史记录仅保留当天。'); }
            if(!response.ok)throw new Error('会话暂时无法恢复');
            const data=await response.json();welcome();threadId=id;byId('aiChatSnapshot').textContent='历史回复 · 再次发送时更新数据快照';
            for(const turn of data.turns||[]){const view=responseView(turn.question);view.event({event:'token',text:turn.answer||''});for(const file of turn.files||[])view.event({event:'file',...file});view.finish('done');}
            resetFollow();scrollLatest(true);
        }catch(error){say(error.message);}
    }
    function resetFollow() { follow = true; byId('aiChatLatest').hidden = true; }
    function newConversation() { stop(); sequence++; activeRun = null; threadId = null; sendingState(); welcome(); resetFollow();byId('aiChatHistory').value='';byId('aiChatSnapshot').textContent=''; say('已开启新对话'); }
    async function send() {
        const input = byId('aiChatInput'); if (!input || activeRun) return;
        if (historyDeadline !== null && performance.now() >= historyDeadline) { newConversation(); loadHistory(); }
        const text = input.value.trim(); if (!text) return; input.value = ''; resetFollow();
        const run = {id:++sequence, controller:new AbortController(), view:responseView(text)}; activeRun = run; sendingState(); let completed = false;
        try {
            const response = await fetch('/api/ai/chat',{method:'POST',credentials:'same-origin',signal:run.controller.signal,headers:{'Content-Type':'application/json','X-CSRFToken':getCSRF()},body:JSON.stringify({message:text,thread_id:threadId})});
            if (!response.ok) {
                let message = '请求失败 (HTTP ' + response.status + ')'; try { const data = await response.json(); if (data.error) message = String(data.error); } catch (_) {} throw new Error(message);
            }
            if (!response.body || !response.headers.get('Content-Type')?.includes('text/event-stream')) throw new Error('未收到有效回复，请检查登录状态后重试。');
            const reader = response.body.getReader(), decoder = new TextDecoder();
            const parser = core.createParser(event => {
                if (sequence !== run.id || run.controller.signal.aborted) return;
                if (event.event === 'thread') {
                    if (event.reset) { run.view.finish('stopped'); welcome(); run.view=responseView(text); }
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
        const launcher = node('button','ai-launcher-btn'); launcher.id = 'aiChatLauncher'; launcher.type = 'button'; launcher.title = 'AI 数据助手'; launcher.setAttribute('aria-label','打开 AI 数据助手'); launcher.setAttribute('aria-controls','aiChatPanel'); launcher.setAttribute('aria-expanded','false'); launcher.innerHTML = icon('ai'); launcher.onclick = toggle;
        const media = window.matchMedia('(max-width:768px)');
        function placeLauncher() {
            const controls = byId('mobileBtnCluster'); const parent = controls && media.matches ? controls : document.body; if (launcher.parentElement !== parent) parent.append(launcher);
            if (panelOpen) { byId('aiChatBackdrop').hidden = !modalMode(); byId('aiChatPanel').setAttribute('aria-modal',String(modalMode())); document.body.classList.toggle('ai-chat-modal-open',modalMode()); }
        }
        const backdrop = node('div','ai-chat-backdrop'); backdrop.id = 'aiChatBackdrop'; backdrop.hidden = true; backdrop.onclick = () => setOpen(false);
        const panel = node('section','ai-chat-panel'); panel.id = 'aiChatPanel'; panel.hidden = true; panel.setAttribute('role','dialog'); panel.setAttribute('aria-labelledby','aiChatTitle'); panel.setAttribute('aria-modal','false');
        panel.innerHTML = '<header class="ai-chat-header"><div class="ai-chat-heading"><span class="ai-header-icon">' + icon('ai') + '</span><div><h2 id="aiChatTitle">AI 数据助手</h2><p>灌溉 · 运维 · 数据分析</p></div></div><div class="ai-header-actions"><button type="button" id="aiChatNew" class="ai-icon-button" title="新建对话" aria-label="新建对话">' + icon('plus') + '</button><button type="button" id="aiChatExpand" class="ai-icon-button" title="展开对话" aria-label="展开对话">' + icon('expand') + '</button><button type="button" id="aiChatClose" class="ai-icon-button" title="关闭" aria-label="关闭 AI 数据助手">' + icon('close') + '</button></div></header><div id="aiChatLive" class="pwa-sr-only" aria-live="polite" aria-atomic="true"></div><div id="aiChatMessages" class="ai-chat-messages" role="log" aria-live="off" aria-label="对话内容"></div><button type="button" id="aiChatLatest" class="ai-latest" hidden>' + icon('chevron-down') + ' 回到最新</button><div class="ai-composer"><label class="pwa-sr-only" for="aiChatInput">发送给 AI 数据助手</label><div class="ai-composer-box"><textarea id="aiChatInput" placeholder="描述你要分析的问题…" rows="1"></textarea><button type="button" id="aiChatSend" aria-label="发送" disabled>' + icon('send') + '</button></div><p class="ai-composer-hint">Enter 发送 · Shift+Enter 换行</p></div>';
        document.body.append(backdrop,panel); placeLauncher(); if (media.addEventListener) media.addEventListener('change',placeLauncher); else media.addListener(placeLauncher);
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
        loadHistory();
        document.addEventListener('visibilitychange', () => { if (!document.hidden) loadHistory(); });
        fitViewport();
        window.visualViewport?.addEventListener('resize',fitViewport,{passive:true});
        window.visualViewport?.addEventListener('scroll',fitViewport,{passive:true});
        byId('aiChatClose').onclick = () => setOpen(false); byId('aiChatNew').onclick = newConversation;
        byId('aiChatExpand').onclick = () => { expanded = !expanded; panel.classList.toggle('is-expanded',expanded); byId('aiChatExpand').innerHTML = icon(expanded ? 'collapse' : 'expand'); byId('aiChatExpand').setAttribute('aria-label',expanded ? '收起对话' : '展开对话'); byId('aiChatExpand').title = expanded ? '收起对话' : '展开对话'; placeLauncher(); };
        byId('aiChatSend').onclick = () => activeRun ? stop() : send();
        const input = byId('aiChatInput'); input.addEventListener('input',resizeInput);
        input.addEventListener('keydown',event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); send(); } });
        const box = byId('aiChatMessages'); box.addEventListener('scroll',() => { follow = box.scrollHeight-box.scrollTop-box.clientHeight < 80; byId('aiChatLatest').hidden = follow; },{passive:true});
        byId('aiChatLatest').onclick = () => { follow = true; scrollLatest(true); byId('aiChatLatest').hidden = true; };
        panel.addEventListener('keydown',event => {
            if (event.key === 'Escape') { event.preventDefault(); setOpen(false); }
            if (event.key !== 'Tab' || !modalMode()) return;
            const focusable = [...panel.querySelectorAll('button,a[href],textarea,select,summary,[tabindex="0"]')].filter(item => !item.disabled && item.getClientRects().length);
            const first = focusable[0], last = focusable[focusable.length-1];
            if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
            else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
        });
        welcome();
    }
    function mountIfAvailable() { fetch('/api/ai/status',{credentials:'same-origin'}).then(response => response.ok ? response.json() : null).then(data => { if (data?.available) mount(data.preview === true); }).catch(() => {}); }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded',mountIfAvailable); else mountIfAvailable();
    window.AIChat = {open:() => setOpen(true),toggle};
})();
