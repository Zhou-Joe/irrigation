/* EnGenie quote review stays inside the current conversation. Extraction never commits inventory. */
(function () {
    'use strict';
    const sessions = new Set();
    const el = (tag, className, text) => {
        const item = document.createElement(tag);
        if (className) item.className = className;
        if (text != null) item.textContent = String(text);
        return item;
    };
    const button = (text, primary) => {
        const item = el('button', 'ivq-button' + (primary ? ' is-primary' : ''), text);
        item.type = 'button'; return item;
    };
    const symbol = name => {
        const item = el('span', 'ivq-symbol');
        item.innerHTML = window.uiIcon ? window.uiIcon(name) : '';
        item.setAttribute('aria-hidden', 'true'); return item;
    };
    let sequence = 0, enabled = true;
    const normalized = value => String(value || '').normalize('NFKC').trim().replace(/\s+/g, ' ').toLocaleLowerCase();
    function historyText(record) {
        if (!record || typeof record !== 'object') return '';
        const price = record.unit_price == null || record.unit_price === '' ? '' : '¥' + String(record.unit_price) + (record.unit ? ' / ' + record.unit : '');
        return [record.supplier, record.date, price].filter(Boolean).join(' · ');
    }

    // A bounded, keyboard-accessible search list replaces long chip or select lists.
    function picker(entries, value, {label, root = false, preferred = [], limit = 5, onSelect}) {
        const wrap = el('div', 'ivq-picker'), input = el('input'), list = el('div', 'ivq-options');
        const id = 'ivq-options-' + (++sequence);
        input.type = 'search'; input.autocomplete = 'off'; input.placeholder = root ? '搜索目录，或选择根层' : '搜索名称、编号或完整路径';
        input.setAttribute('role', 'combobox'); input.setAttribute('aria-label', label);
        input.setAttribute('aria-expanded', 'false'); input.setAttribute('aria-autocomplete', 'list'); input.setAttribute('aria-controls', id);
        list.id = id; list.setAttribute('role', 'listbox'); list.setAttribute('aria-label', label); list.hidden = true;
        let selected = entries.find(item => String(item.id) === String(value));
        input.value = selected ? selected.path || selected.name : root ? '根层（稍后整理）' : '';
        let options = [], active = -1, blurTimer = null;
        function close() { list.hidden = true; input.setAttribute('aria-expanded', 'false'); input.removeAttribute('aria-activedescendant'); active = -1; }
        function choose(item) {
            selected = item;
            input.value = item ? item.path || item.name : '根层（稍后整理）';
            onSelect(item); close();
        }
        function highlight(index) {
            active = index;
            [...list.querySelectorAll('[role=option]')].forEach((option, i) => option.setAttribute('aria-selected', String(i === active)));
            const option = list.querySelectorAll('[role=option]')[active];
            if (option) { input.setAttribute('aria-activedescendant', option.id); option.scrollIntoView({block:'nearest'}); }
        }
        function show() {
            clearTimeout(blurTimer); list.replaceChildren(); active = -1;
            const query = input.value.trim().toLocaleLowerCase();
            const initial = query === (selected?.path || selected?.name || '').toLocaleLowerCase() || query === '根层（稍后整理）';
            const matches = entries.filter(item => initial || !query || [item.name, item.code, item.path].join(' ').toLocaleLowerCase().includes(query));
            if (!query || initial) {
                const rank = item => { const index = preferred.indexOf(String(item.id)); return index < 0 ? preferred.length : index; };
                matches.sort((a, b) => rank(a) - rank(b));
            }
            options = (root ? [null] : []).concat(matches.slice(0, limit));
            options.forEach((item, index) => {
                const option = el('div', 'ivq-option'); option.id = id + '-' + index; option.setAttribute('role', 'option'); option.setAttribute('aria-selected', 'false');
                option.append(el('strong', '', item ? item.name + (item.code ? ' · ' + item.code : '') : '根层（稍后整理）'));
                if (item) {
                    option.append(el('small', '', item.path || item.name));
                    if (item.unit) option.append(el('small', '', '系统单位：' + item.unit));
                }
                option.addEventListener('pointerdown', event => event.preventDefault());
                option.onclick = () => choose(item); list.append(option);
            });
            if (!options.length) list.append(el('p', 'ivq-option-empty', '没有找到部件，可改为“新建部件”。'));
            else if (matches.length > limit) list.append(el('p', 'ivq-option-empty', '显示前 ' + limit + ' 项，请输入更多关键字缩小范围。'));
            list.hidden = false; input.setAttribute('aria-expanded', 'true');
        }
        input.addEventListener('focus', () => { input.select(); show(); });
        input.addEventListener('input', () => { selected = null; onSelect(null); show(); });
        input.addEventListener('blur', () => { blurTimer = setTimeout(close, 120); });
        input.addEventListener('keydown', event => {
            if (event.key === 'Escape' && !list.hidden) { event.preventDefault(); event.stopPropagation(); close(); }
            else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                event.preventDefault(); if (list.hidden) show();
                if (options.length) highlight(Math.max(0, Math.min(options.length - 1, active + (event.key === 'ArrowDown' ? 1 : -1))));
            } else if (event.key === 'Enter') {
                event.preventDefault(); event.stopPropagation();
                if (!list.hidden && options.length && (active >= 0 || options.length === 1)) choose(options[Math.max(0, active)]);
            }
        });
        wrap.append(input, list); return wrap;
    }

    function mount({host, csrf, onChange = () => {}, onStatus = () => {}, onBusy = () => {}, file = null, draft = null, restore = false}) {
        const card = el('section', 'ivq-card'); card.setAttribute('aria-label', 'EnGenie 报价提取与确认');
        const title = el('div', 'ivq-heading'); title.append(symbol('file'), el('strong', '', '报价提取'));
        const status = el('div', 'ivq-status'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
        const pause = el('p', 'ivq-pause', '报价操作已暂停，请切回灌溉业务后继续。'); pause.hidden = true;
        const source = el('form', 'ivq-source'), sourceFields = el('fieldset');
        const review = el('form', 'ivq-review'); review.hidden = true;
        const result = el('div', 'ivq-result'); result.hidden = true;
        card.append(title, status, pause, source, review, result); host.append(card);
        const state = {phase:'source', controller:null, payload:null, token:null, key:null, rows:[], catalog:[],
            supplierChoice:'pending', supplierName:'', sourceMode:file ? 'file' : 'text'};
        let disposed = false, selectedFile = file;
        const notify = () => { if (!disposed) { onChange(); onBusy(); } };
        function setStatus(message, kind = '') {
            status.className = 'ivq-status' + (kind ? ' is-' + kind : ''); status.replaceChildren();
            if (kind === 'busy') { const spinner = el('span', 'ai-spin-ring'); spinner.setAttribute('aria-hidden', 'true'); status.append(spinner); }
            else if (kind) status.append(symbol(kind === 'success' ? 'check' : 'alert'));
            status.append(el('span', '', message)); onStatus(message);
        }
        function phase(value) { state.phase = value; card.dataset.state = value; notify(); }
        function syncEnabled() {
            card.inert = !enabled; pause.hidden = enabled;
            sourceFields.disabled = !enabled || state.phase === 'extracting';
            const fields = review.querySelector('fieldset');
            if (fields) fields.disabled = !enabled || ['saving','uncertain','checking'].includes(state.phase);
            if (confirmButton) confirmButton.disabled = !enabled || state.phase === 'saving' || state.phase === 'checking' ||
                state.phase !== 'uncertain' && (state.supplierChoice === 'pending' || !supplier?.value.trim() || state.rows.some(unresolved) || !state.rows.some(row => row.action !== 'skip'));
        }
        async function request(url, body, signal) {
            let response;
            try {
                response = await fetch(url, {method:'POST', credentials:'same-origin', signal,
                    headers:{'X-CSRFToken':typeof csrf === 'function' ? csrf() : csrf || '', 'X-Requested-With':'XMLHttpRequest'}, body});
            } catch (error) { error.uncertain = error.name !== 'AbortError'; throw error; }
            let data;
            try { data = await response.json(); }
            catch (_) {
                const error = new Error('未收到有效结果，请检查登录或网络状态。');
                error.uncertain = response.ok || response.status >= 500; throw error;
            }
            if (!response.ok || !data.success) {
                const error = new Error(data.message || data.error || '操作失败，请重试。');
                error.uncertain = data.uncertain === true || response.status >= 500; throw error;
            }
            return data;
        }
        const tabs = el('div', 'ivq-source-tabs');
        const textTab = button('粘贴报价'), fileTab = button('上传文件');
        const textLabel = el('label', 'ivq-field'), text = el('textarea');
        text.rows = 6; text.placeholder = '粘贴包含物料、单价、供应商和日期的报价内容…';
        textLabel.append(el('span', '', '报价内容'), text);
        const fileArea = el('div', 'ivq-file-area'), fileInput = el('input');
        fileInput.type = 'file'; fileInput.accept = '.xlsx,.csv,.txt,.pdf'; fileInput.setAttribute('aria-label', '选择报价文件');
        const fileName = el('p', 'ivq-file-name', file ? file.name : '尚未选择文件');
        fileInput.onchange = () => { selectedFile = fileInput.files[0] || null; fileName.textContent = selectedFile ? selectedFile.name : '尚未选择文件'; };
        fileArea.append(fileInput, fileName, el('p', 'ivq-hint', '支持 Excel、CSV、TXT 和文字型 PDF；扫描图片或扫描 PDF 暂不支持。'));
        function sourceMode(mode) {
            state.sourceMode = mode; textLabel.hidden = mode !== 'text'; fileArea.hidden = mode !== 'file';
            textTab.setAttribute('aria-pressed', String(mode === 'text')); fileTab.setAttribute('aria-pressed', String(mode === 'file'));
        }
        textTab.onclick = () => { sourceMode('text'); text.focus(); }; fileTab.onclick = () => sourceMode('file');
        tabs.append(textTab, fileTab);
        const extractButton = button('提取并预览', true); extractButton.type = 'submit';
        const cancel = button('取消');
        const sourceActions = el('div', 'ivq-actions'); sourceActions.append(cancel, extractButton);
        sourceFields.append(tabs, textLabel, fileArea, el('p', 'ivq-hint', '先提取、逐行核对，点击“确认写入”后才保存到库存。'), sourceActions);
        source.append(sourceFields); sourceMode(state.sourceMode);
        const abortButton = button('取消提取'); abortButton.hidden = true; source.append(abortButton);
        function cancelDraft() {
            if (state.phase === 'saving' || state.phase === 'uncertain') return;
            state.controller?.abort(); source.hidden = true; review.hidden = true; abortButton.hidden = true;
            phase('cancelled'); setStatus('已取消，未写入库存。'); notify();
        }
        cancel.onclick = cancelDraft; abortButton.onclick = cancelDraft;
        source.onsubmit = event => { event.preventDefault(); extract(); };

        async function extract() {
            if (!enabled || state.phase === 'extracting' || state.phase === 'saving' || state.phase === 'uncertain') return;
            const body = new FormData();
            if (state.sourceMode === 'file') {
                if (!selectedFile) { setStatus('请选择一个报价文件。', 'error'); fileInput.focus(); return; }
                if (!/\.(xlsx|csv|txt|pdf)$/i.test(selectedFile.name)) { setStatus('请选择 Excel、CSV、TXT 或文字型 PDF。', 'error'); return; }
                body.append('file', selectedFile);
            } else {
                if (!text.value.trim()) { setStatus('请先粘贴报价内容。', 'error'); text.focus(); return; }
                body.append('text', text.value.trim());
            }
            state.controller = new AbortController(); phase('extracting'); syncEnabled(); abortButton.hidden = false;
            setStatus('EnGenie 正在读取报价并匹配库存目录…', 'busy');
            try {
                const data = await request('/inventory/quotes/extract/', body, state.controller.signal);
                if (disposed || state.phase !== 'extracting') return;
                acceptDraft(data);
                review.querySelector('input')?.focus(); notify();
            } catch (error) {
                if (disposed || error.name === 'AbortError' || state.phase !== 'extracting') return;
                phase('source'); setStatus(error.message || '网络连接中断，报价未保存，可重试提取。', 'error');
            } finally { if (!disposed) { abortButton.hidden = true; syncEnabled(); notify(); } }
        }

        function field(label, input) { const wrap = el('label', 'ivq-field'); wrap.append(el('span', '', label), input); return wrap; }
        function input(value, {type = 'text', required = false} = {}) {
            const item = el('input'); item.type = type; item.value = value || ''; item.required = required; return item;
        }
        let summary, confirmButton, editSource, supplier, quoteDate, readiness;
        function unresolved(row) { return row.action === 'pending' || row.action === 'existing' && !row.category_id; }
        function acceptDraft(data) {
            if (!data.token || !data.submission_key || !Array.isArray(data.items) || !data.items.length) throw new Error('没有可核对的报价项目，请在对话中说明需要重新提取。');
            state.token = data.token; state.key = data.submission_key; state.payload = null;
            state.catalog = Array.isArray(data.catalog) ? data.catalog : [];
            const parts = new Map(state.catalog.filter(item => item.node_type === 'part').map(item => [String(item.id), item]));
            state.rows = data.items.map(item => {
                const suggested = item.suggested_category_id ?? item.category_id;
                const selected = suggested && parts.get(String(suggested));
                const candidates = [], seen = new Set();
                for (const candidate of Array.isArray(item.candidates) ? item.candidates : []) {
                    const part = parts.get(String(candidate.id));
                    if (!part || seen.has(String(part.id))) continue;
                    seen.add(String(part.id)); candidates.push({...candidate, ...part, supplier_history:candidate.supplier_history});
                    if (candidates.length === 5) break;
                }
                if (selected && !seen.has(String(selected.id))) candidates.unshift({...selected, reason:item.match_reason || item.match_label || '建议复用已有部件'});
                return {...item, action:selected ? 'existing' : 'pending', category_id:selected?.id || '', suggested_id:selected?.id || '',
                    candidates:candidates.slice(0,5), parent_id:'', name:String(item.name || ''), code:String(item.code || ''),
                    unit:String(item.unit || ''), unit_price:String(item.unit_price ?? ''), source_code:String(item.code || ''), source_unit:String(item.unit || ''), source_unit_price:String(item.unit_price ?? '')};
            });
            source.hidden = true; abortButton.hidden = true; renderReview(data);
            phase('review'); syncEnabled(); setStatus('提取完成，请核对每一行；点击确认前不会写入库存。', 'success');
        }
        function countSummary() {
            if (!summary) return;
            const existing = state.rows.filter(row => row.action === 'existing' && row.category_id).length, fresh = state.rows.filter(row => row.action === 'new').length;
            const pending = state.rows.filter(unresolved).length, skipped = state.rows.filter(row => row.action === 'skip').length;
            summary.textContent = '共 ' + state.rows.length + ' 行 · 匹配现有 ' + existing + ' · 新建 ' + fresh + ' · 待选择 ' + pending + ' · 跳过 ' + skipped;
            if (confirmButton && !['uncertain','saving','checking'].includes(state.phase)) confirmButton.textContent = '确认写入 ' + (existing + fresh) + ' 项';
            if (readiness) {
                const missing = [];
                if (state.supplierChoice === 'pending' || !supplier.value.trim()) missing.push('选择历史供应商，或明确按填写的名称记录');
                if (pending) missing.push('完成 ' + pending + ' 行部件匹配 / 新建 / 跳过选择');
                if (!state.rows.some(row => row.action !== 'skip')) missing.push('至少保留一项报价');
                readiness.textContent = missing.length ? '确认前请先' + missing.join('；') + '。' : '匹配选择已完成，核对价格与日期后可确认写入。';
                readiness.dataset.ready = String(!missing.length);
            }
            syncEnabled();
        }
        function supplierControl(data) {
            const wrap = el('div', 'ivq-supplier-control'), frame = el('div', 'ivq-picker'), options = el('div', 'ivq-options');
            const status = el('p', 'ivq-supplier-state'), sourceName = String(data.source_supplier ?? data.supplier ?? '');
            const candidates = Array.isArray(data.supplier_candidates) ? data.supplier_candidates.slice(0,5) : [];
            const history = new Map();
            for (const item of [...candidates, ...(Array.isArray(data.supplier_catalog) ? data.supplier_catalog.slice(0,200) : [])]) {
                if (item && typeof item.name === 'string' && item.name.trim() && !history.has(normalized(item.name))) history.set(normalized(item.name), item);
            }
            const entries = [...history.values()], suggested = history.get(normalized(data.suggested_supplier));
            const initial = suggested || (data.supplier_match_status === 'exact' ? history.get(normalized(data.supplier)) : null);
            supplier = input(initial?.name || data.supplier || sourceName, {required:true}); supplier.maxLength = 200; supplier.type = 'search'; supplier.autocomplete = 'off';
            const id = 'ivq-supplier-' + (++sequence);
            supplier.id = id + '-input'; supplier.setAttribute('role','combobox'); supplier.setAttribute('aria-label','搜索或填写供应商'); supplier.setAttribute('aria-autocomplete','list'); supplier.setAttribute('aria-controls',id); supplier.setAttribute('aria-expanded','false');
            options.id = id; options.setAttribute('role','listbox'); options.setAttribute('aria-label','历史供应商候选'); options.hidden = true;
            state.supplierChoice = initial ? 'existing' : 'pending'; state.supplierName = initial?.name || '';
            let choices = [], active = -1, blurTimer = null, touched = false;
            function close() { options.hidden = true; supplier.setAttribute('aria-expanded','false'); supplier.removeAttribute('aria-activedescendant'); active = -1; }
            function feedback(reason = '') {
                status.textContent = state.supplierChoice === 'existing' ? '复用历史名称：' + state.supplierName + (reason ? ' · ' + reason : '') :
                    state.supplierChoice === 'new' ? '将按填写的名称记录：' + supplier.value.trim() : '待选择：可复用历史供应商，或明确按填写的名称记录。';
                status.dataset.choice = state.supplierChoice; countSummary();
            }
            function choose(choice) {
                if (choice.item) { supplier.value = choice.item.name; state.supplierChoice = 'existing'; state.supplierName = choice.item.name; }
                else { state.supplierChoice = 'new'; state.supplierName = ''; }
                feedback(choice.item?.reason || ''); close(); supplier.focus();
            }
            function show() {
                clearTimeout(blurTimer); options.replaceChildren(); active = -1;
                const query = normalized(supplier.value), selected = state.supplierChoice === 'existing' && query === normalized(state.supplierName);
                const matches = entries.filter(item => selected || !touched || !query || normalized(item.name).includes(query));
                choices = matches.slice(0,5).map(item => ({item}));
                if (supplier.value.trim() && !history.has(query)) choices.push({item:null});
                choices.forEach((choice, index) => {
                    const option = el('div', 'ivq-option' + (!choice.item ? ' is-manual' : '')); option.id = id + '-' + index; option.setAttribute('role','option'); option.setAttribute('aria-selected','false');
                    option.append(el('strong','',choice.item ? choice.item.name : '按填写的名称记录：' + supplier.value.trim()));
                    if (choice.item) {
                        if (choice.item.reason) option.append(el('small','',choice.item.reason));
                        const count = typeof choice.item.matched_parts === 'number' ? '关联部件 ' + choice.item.matched_parts + ' 项' : '';
                        const date = choice.item.last_quote_date ? '最近报价 ' + choice.item.last_quote_date : '';
                        if (count || date) option.append(el('small','',[count,date].filter(Boolean).join(' · ')));
                    } else option.append(el('small','','已核对历史候选，明确使用当前填写的名称。'));
                    option.addEventListener('pointerdown', event => event.preventDefault()); option.onclick = () => choose(choice); options.append(option);
                });
                if (!choices.length) options.append(el('p','ivq-option-empty','暂无历史候选，请填写原报价供应商名称。'));
                if (matches.length > 5) options.append(el('p','ivq-option-empty','显示前 5 个历史名称，输入更多关键字继续搜索。'));
                options.hidden = false; supplier.setAttribute('aria-expanded','true');
            }
            supplier.addEventListener('focus', () => { supplier.select(); show(); });
            supplier.addEventListener('input', () => {
                supplier.setCustomValidity(''); touched = true; const exact = history.get(normalized(supplier.value));
                state.supplierChoice = exact ? 'existing' : 'pending'; state.supplierName = exact?.name || ''; feedback(exact?.reason || ''); show();
            });
            supplier.addEventListener('blur', () => { blurTimer = setTimeout(close,120); });
            supplier.addEventListener('keydown', event => {
                if (event.key === 'Escape' && !options.hidden) { event.preventDefault(); event.stopPropagation(); close(); }
                else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                    event.preventDefault(); if (options.hidden) show(); active = Math.max(0,Math.min(choices.length-1,active+(event.key === 'ArrowDown' ? 1 : -1)));
                    [...options.querySelectorAll('[role=option]')].forEach((option,index) => option.setAttribute('aria-selected',String(index === active)));
                    const option = options.querySelectorAll('[role=option]')[active]; if (option) { supplier.setAttribute('aria-activedescendant',option.id); option.scrollIntoView({block:'nearest'}); }
                } else if (event.key === 'Enter') {
                    event.preventDefault(); event.stopPropagation(); if (!options.hidden && choices.length && (active >= 0 || choices.length === 1)) choose(choices[Math.max(0,active)]);
                }
            });
            frame.append(supplier,options); wrap.append(frame);
            wrap.append(el('p','ivq-source-supplier','原报价名称：' + (sourceName || '未提供')));
            if (data.supplier_match_reason) wrap.append(el('p','ivq-match-reason',data.supplier_match_reason));
            wrap.append(status); feedback(initial?.reason || ''); return wrap;
        }
        function renderReview(data) {
            review.replaceChildren(); review.hidden = false;
            const fields = el('fieldset'), meta = el('div', 'ivq-meta-grid');
            quoteDate = input(data.quote_date, {type:'date', required:true});
            const supplierField = el('div','ivq-field'); supplierField.append(el('span','','供应商（必填）'),supplierControl(data));
            meta.append(supplierField, field('报价日期（必填）', quoteDate)); fields.append(meta);
            summary = el('p', 'ivq-summary'); fields.append(summary);
            if (Array.isArray(data.warnings) && data.warnings.length) {
                const warning = el('details', 'ivq-warnings'); warning.open = true;
                warning.append(el('summary', '', '提取提示 · ' + data.warnings.length));
                const list = el('ul'); data.warnings.forEach(message => list.append(el('li', '', message))); warning.append(list); fields.append(warning);
            }
            fields.append(el('p', 'ivq-hint', '优先核对推荐的现有部件与历史供应商。待选择项目须明确匹配、新建或跳过；新建时可选择上级目录。匹配部件只添加本次历史报价，不移动或改名，也不替换原报价单价。'));
            const rows = el('div', 'ivq-rows'); state.rows.forEach((row, index) => rows.append(renderRow(row, index))); fields.append(rows);
            const warning = el('p', 'ivq-commit-note', '请核对供应商、日期、部件与单价。下方按钮会正式新建部件并记录报价。');
            readiness = el('p','ivq-readiness'); readiness.setAttribute('role','status'); readiness.setAttribute('aria-live','polite');
            const actions = el('div', 'ivq-actions'); editSource = button('更换报价内容'); const discard = button('取消'); confirmButton = button('确认写入', true); confirmButton.type = 'submit';
            editSource.hidden = !!draft;
            editSource.onclick = () => { review.hidden = true; source.hidden = false; phase('source'); setStatus('可更换报价内容并重新提取；原预览未写入。'); syncEnabled(); notify(); };
            discard.onclick = cancelDraft; actions.append(discard, editSource);
            fields.append(actions); review.append(fields, warning, readiness, confirmButton); countSummary();
            review.onsubmit = event => { event.preventDefault(); confirm(); };
        }
        function renderRow(row, index) {
            const article = el('article', 'ivq-row'); article.dataset.action = row.action;
            const heading = el('div', 'ivq-row-heading'), action = el('select'); action.setAttribute('aria-label', '第 ' + (index + 1) + ' 行处理方式');
            [['pending','待选择匹配方式'], ['existing','匹配现有部件'], ['new','明确新建部件'], ['skip','跳过此行']].forEach(([value, label]) => action.add(new Option(label, value)));
            action.value = row.action; heading.append(el('strong', '', (index + 1) + '. ' + (row.name || '未命名物料')), action);
            const sourcePath = el('p', 'ivq-path'); sourcePath.append(el('span', '', '原报价层级'), el('span', '', row.source_path || '未提供'));
            const sourceInfo = el('p','ivq-source-info','原单编码：' + (row.source_code || '未提供') + ' · 原单单位：' + (row.source_unit || '未提供') + ' · 原单单价：' + (row.source_unit_price ? '¥' + row.source_unit_price : '未提供'));
            const body = el('div', 'ivq-row-body'), systemPath = el('p', 'ivq-path is-system');
            const fields = el('div', 'ivq-row-fields');
            function updatePath() {
                const chosen = state.catalog.find(item => String(item.id) === String(row.action === 'existing' ? row.category_id : row.parent_id));
                systemPath.replaceChildren(el('span', '', '系统目录'));
                systemPath.append(el('span', '', row.action === 'existing' ? chosen?.path || '请搜索并选择现有部件' : row.action === 'pending' ? '尚未选择，不会自动新建' : (chosen?.path || '根层') + ' / ' + (row.name || '新部件')));
                for (const option of body.querySelectorAll('.ivq-candidate')) {
                    const selected = row.action === 'existing' && option.dataset.categoryId === String(row.category_id);
                    option.setAttribute('aria-pressed',String(selected));
                    option.querySelector('.ivq-candidate-badge').textContent = selected ? '已选择' : option.dataset.priority;
                }
            }
            function choosePart(candidate) {
                row.action = 'existing'; row.category_id = candidate.id; action.value = 'existing';
                renderBody(); countSummary(); notify(); action.focus();
            }
            function candidateList() {
                if (!row.candidates.length) return null;
                const details = el('details','ivq-candidates'); details.open = row.action === 'pending' || row.action === 'existing' && !row.category_id;
                details.append(el('summary','','推荐现有部件 · ' + row.candidates.length + ' 个候选'));
                const list = el('div','ivq-candidate-options');
                for (const candidate of row.candidates) {
                    const item = button('',false); item.className = 'ivq-candidate';
                    item.dataset.categoryId = String(candidate.id); item.dataset.priority = candidate.confidence === 'high' ? '优先候选' : '可选候选';
                    item.setAttribute('aria-pressed',String(row.action === 'existing' && String(candidate.id) === String(row.category_id)));
                    const heading = el('span','ivq-candidate-heading'); heading.append(el('strong','',candidate.name));
                    const chosen = row.action === 'existing' && String(candidate.id) === String(row.category_id);
                    heading.append(el('span','ivq-candidate-badge',chosen ? '已选择' : candidate.confidence === 'high' ? '优先候选' : '可选候选'));
                    item.append(heading,el('span','ivq-candidate-path',candidate.path || candidate.name));
                    item.append(el('span','ivq-candidate-meta','系统编码：' + (candidate.code || '未设置') + ' · 系统单位：' + (candidate.unit || '未设置')));
                    if (candidate.reason) item.append(el('span','ivq-candidate-reason',candidate.reason));
                    const history = (Array.isArray(candidate.supplier_history) && candidate.supplier_history.length ? candidate.supplier_history : candidate.last_price ? [candidate.last_price] : []).slice(0,2);
                    for (const record of history) {
                        const label = historyText(record); if (label) item.append(el('span','ivq-candidate-history','历史报价：' + label));
                    }
                    item.onclick = () => choosePart(candidate); list.append(item);
                }
                details.append(list); return details;
            }
            function selectedInfo() {
                const part = state.catalog.find(item => String(item.id) === String(row.category_id));
                if (!part) return null;
                const candidate = row.candidates.find(item => String(item.id) === String(part.id));
                const info = el('div','ivq-selected-part'); info.append(el('strong','',part.name + (part.code ? ' · ' + part.code : '')));
                const reason = candidate?.reason || (String(row.suggested_id) === String(part.id) ? row.match_reason || row.match_label : '') || '已手动选择现有部件，请核对型号、规格与计价单位。';
                info.append(el('p','ivq-match-reason',reason));
                const recent = candidate?.last_price || candidate?.supplier_history?.[0];
                if (historyText(recent)) info.append(el('p','ivq-candidate-history','历史参考：' + historyText(recent)));
                if (row.source_unit && part.unit && normalized(row.source_unit) !== normalized(part.unit)) info.append(el('p','ivq-unit-warning','原单单位「' + row.source_unit + '」与系统单位「' + part.unit + '」不同，请核对计价单位；未自动换算。'));
                return info;
            }
            function renderBody() {
                body.replaceChildren(); fields.replaceChildren(); article.dataset.action = row.action;
                if (row.action === 'skip') { body.append(el('p', 'ivq-hint', '此行不会写入库存。')); return; }
                const candidates = candidateList(); if (candidates) body.append(candidates);
                if (row.action === 'pending') {
                    body.prepend(el('p','ivq-pending-note',row.candidates.length ? '请选择推荐的现有部件，或搜索其他部件；确认没有对应部件时再新建。' : '尚无明确匹配。请搜索现有目录，或明确选择新建部件。'));
                    const actions = el('div','ivq-pending-actions'), search = button('搜索现有部件'), create = button('明确新建部件');
                    search.onclick = () => { row.action = 'existing'; action.value = 'existing'; renderBody(); countSummary(); notify(); body.querySelector('.ivq-picker input')?.focus(); };
                    create.onclick = () => { row.action = 'new'; action.value = 'new'; renderBody(); countSummary(); notify(); body.querySelector('.ivq-row-fields input')?.focus(); };
                    actions.append(search,create); body.append(actions,systemPath); updatePath(); return;
                }
                if (row.action === 'existing') { const info = selectedInfo(); if (info) body.prepend(info); }
                const matchLabel = el('div', 'ivq-field');
                matchLabel.append(el('span', '', row.action === 'existing' ? '匹配系统部件' : '新部件的上级目录（可选）'));
                matchLabel.append(picker(state.catalog.filter(item => row.action === 'existing' ? item.node_type === 'part' : item.node_type !== 'part'), row.action === 'existing' ? row.category_id : row.parent_id,
                    {label:row.action === 'existing' ? '搜索现有部件' : '搜索上级目录', root:row.action === 'new', limit:row.action === 'new' ? 30 : 5, preferred:row.candidates.map(item => String(item.id)), onSelect(item) {
                        if (row.action === 'existing') row.category_id = item ? item.id : '';
                        else row.parent_id = item ? item.id : '';
                        const previous = body.querySelector('.ivq-selected-part'); previous?.remove();
                        if (row.action === 'existing') { const info = selectedInfo(); if (info) body.prepend(info); }
                        updatePath(); countSummary();
                    }}));
                body.append(matchLabel, systemPath);
                if (row.action === 'new') {
                    const name = input(row.name, {required:true}), code = input(row.code);
                    name.oninput = () => { row.name = name.value; updatePath(); }; code.oninput = () => { row.code = code.value; };
                    fields.append(field('新部件名称', name), field('编号（可选）', code));
                }
                const unit = input(row.unit), price = input(row.unit_price);
                unit.oninput = () => { row.unit = unit.value; }; price.inputMode = 'decimal'; price.placeholder = '如 12.50';
                price.oninput = () => { row.unit_price = price.value; price.setCustomValidity(''); };
                fields.append(field('单位', unit), field('单价（元，可留空）', price)); body.append(fields); updatePath();
            }
            action.onchange = () => { row.action = action.value; renderBody(); countSummary(); notify(); };
            renderBody(); article.append(heading, sourcePath, sourceInfo, body); return article;
        }
        function snapshot() {
            if (!review.reportValidity()) return null;
            if (!supplier.value.trim() || state.supplierChoice === 'pending') { setStatus('请先选择历史供应商，或明确按填写的名称记录。','error'); supplier.focus(); return null; }
            const rows = state.rows.filter(row => row.action !== 'skip');
            if (!rows.length) { setStatus('请至少保留一项报价。', 'error'); return null; }
            for (const row of rows) {
                const index = state.rows.indexOf(row) + 1;
                if (row.action === 'pending') { setStatus('第 ' + index + ' 行仍待选择，请匹配、新建或跳过。','error'); review.querySelectorAll('.ivq-row-heading select')[index - 1]?.focus(); return null; }
                if (row.action === 'existing' && !row.category_id) { setStatus('第 ' + index + ' 行尚未选择现有部件。', 'error'); return null; }
                if (row.action === 'new' && !row.name.trim()) { setStatus('请填写第 ' + index + ' 行的新部件名称。', 'error'); return null; }
                if (row.unit_price.trim() && (!/^\d{1,10}(?:\.\d{1,2})?$/.test(row.unit_price.trim()) || Number(row.unit_price.trim()) > 9999999999.99)) {
                    setStatus('第 ' + index + ' 行单价须为 0～9,999,999,999.99，最多两位小数；也可留空。', 'error'); return null;
                }
            }
            return {token:state.token, submission_key:state.key, supplier:state.supplierChoice === 'existing' ? state.supplierName : supplier.value.trim(), quote_date:quoteDate.value, confirmed:'yes',
                items:JSON.stringify(state.rows.map(row => ({row_id:row.row_id, action:row.action, category_id:row.category_id || '', parent_id:row.parent_id || '', name:row.name.trim(), code:row.code.trim(), unit:row.unit.trim(), unit_price:row.unit_price.trim()})))};
        }
        function displayResult(data, refresh = true) {
            phase('success'); review.hidden = true; source.hidden = true; result.hidden = false; result.replaceChildren();
            setStatus(data.message || '报价已写入库存。', 'success');
            const created = Array.isArray(data.created_parts) ? data.created_parts : [];
            result.append(el('p', 'ivq-summary', '新增部件 ' + (created.length || data.created_parts_count || 0) + ' · 添加报价 ' + (data.prices_added || 0) + ' · 已有报价 ' + (data.duplicate_prices || 0)));
            const roots = created.filter(part => !part.parent_id);
            if (roots.length) {
                result.append(el('p', 'ivq-hint', '以下部件创建时位于根层，可展开查看并关联目录。'));
                roots.forEach(part => {
                    const line = el('div', 'ivq-created-part'); line.append(el('strong', '', part.name)); result.append(line);
                    if (window.FOSInventoryMove) {
                        const organize = button('关联目录'), host = el('div'); host.hidden = true;
                        let control = null; line.append(organize, host);
                        organize.onclick = () => {
                            host.hidden = !host.hidden; organize.textContent = host.hidden ? '关联目录' : '收起目录选择';
                            if (!control) control = window.FOSInventoryMove.mount(host, {partId:part.id, onMoved:notify});
                            notify();
                        };
                        moveControls.push(() => control?.destroy());
                    }
                });
            }
            if (refresh) {
                document.dispatchEvent(new CustomEvent('inventory:catalog-changed', {detail:{source:'quote', created_parts:created}}));
                if (window.ivJstree) window.ivJstree.jstree(true).refresh();
                if (window._ivCurrentPartId && typeof window.ivJstreeLoadDetail === 'function') window.ivJstreeLoadDetail(window._ivCurrentPartId);
            }
            notify();
        }
        async function readReceipt() {
            const response = await fetch('/api/submissions/' + encodeURIComponent(state.key) + '/', {credentials:'same-origin', cache:'no-store'});
            const receipt = response.ok ? await response.json() : null;
            return receipt?.found && receipt.kind === 'inventory.quote.confirm' && receipt.result?.success ? receipt.result : null;
        }
        async function restoreResult() {
            phase('checking'); syncEnabled(); setStatus('正在读取这份报价的确认状态…', 'busy');
            try {
                const data = await readReceipt(); if (disposed || state.phase !== 'checking') return;
                if (data) displayResult(data, false);
                else { phase('review'); setStatus('这份报价尚未找到确认记录。草稿仅保留 1 小时，过期后请在对话中要求重新提取。'); }
            } catch (_) {
                if (!disposed && state.phase === 'checking') { phase('review'); setStatus('确认状态暂时无法读取；提交时会按原编号核对，避免重复写入。'); }
            } finally { if (!disposed) { syncEnabled(); notify(); } }
        }
        async function confirm() {
            if (!enabled || state.phase === 'saving') return;
            const retry = state.phase === 'uncertain';
            if (state.phase !== 'uncertain') { if (state.phase !== 'review') return; state.payload = snapshot(); }
            if (!state.payload) return;
            const body = new FormData(); Object.entries(state.payload).forEach(([key, value]) => body.append(key, value));
            phase('saving'); syncEnabled(); confirmButton.disabled = true;
            confirmButton.textContent = '正在确认写入…'; setStatus('正在确认报价，请稍候…', 'busy');
            try {
                let data = null;
                if (retry || restore) {
                    // A committed receipt remains useful even after the extraction draft expires.
                    try {
                        data = await readReceipt();
                    } catch (_) { /* Replay the unchanged submission if its receipt is not available. */ }
                }
                if (!data) data = await request('/inventory/quotes/confirm/', body);
                if (disposed) return;
                displayResult(data);
            } catch (error) {
                if (disposed) return;
                phase(error.uncertain ? 'uncertain' : 'review');
                setStatus(error.uncertain ? '连接中断，写入结果尚未确定。已保留本次内容和提交编号，请点“重试确认结果”，避免重新导入。' : error.message || '未能保存，请核对后再确认。', 'error');
                confirmButton.textContent = error.uncertain ? '重试确认结果' : '确认写入';
                if (!error.uncertain) state.payload = null;
            } finally { if (!disposed) { confirmButton.disabled = !enabled; syncEnabled(); notify(); } }
        }
        const moveControls = [];
        const session = {
            card, get phase() { return state.phase; },
            setEnabled(value) {
                if (!value && state.phase === 'extracting') {
                    state.controller?.abort(); phase('source'); abortButton.hidden = true;
                    setStatus('业务已切换，提取已暂停；切回后可重试。');
                }
                syncEnabled();
            },
            destroy() { disposed = true; state.controller?.abort(); moveControls.forEach(destroy => destroy()); sessions.delete(session); }
        };
        sessions.add(session); phase('source'); syncEnabled();
        if (draft) {
            try { acceptDraft(draft); if (restore) restoreResult(); }
            catch (error) { source.hidden = true; phase('cancelled'); setStatus(error.message, 'error'); }
        } else if (file && enabled) extract();
        else if (enabled) text.focus();
        return session;
    }
    window.EnGenieQuotes = {
        mount,
        isBlocking:() => [...sessions].some(session => ['extracting','saving','uncertain','checking'].includes(session.phase)),
        retainPending(all = false) {
            const keep = new Set();
            for (const session of sessions) {
                if (all || session.phase === 'saving' || session.phase === 'uncertain') keep.add(session.card.closest('.ai-msg') || session.card);
            }
            for (const session of sessions) if (!keep.has(session.card.closest('.ai-msg') || session.card)) session.destroy();
            return [...keep];
        },
        setEnabled(value) { enabled = !!value; sessions.forEach(session => session.setEnabled(enabled)); }
    };
})();
