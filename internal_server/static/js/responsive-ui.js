/* Shared page enhancements. Existing handlers own navigation and business data. */
(() => {
    'use strict';
    const tables = 'table.app-table,table.user-table,table.card-table,table.zone-table,table.zd-table,table.cr-data-table,table.iv-price-table,table.stats-table,table.params,table.rest,table.iv-ledger,table.pm-orders-table,table.matrix-table,table.sh-table';
    const existingScrollers = '.app-table-wrap,.zone-table-container,.ui-table-scroll,.iv-ledger-wrap,.sh-table-scroll';
    const groupSelector = '.app-tabs,.pm-subtabs,.wr-subtabs,.filter-tabs,.view-toggle,.irrig-metric-toggle,.pdxf-tabs';
    const regions = new Map(), groups = new Set(), pendingTables = new Set(), initialized = new WeakSet();
    let queued = false, tabSequence = 0;
    const attr = (element,name,value) => { if (element.getAttribute(name) !== String(value)) element.setAttribute(name,String(value)); };
    const role = (element,value) => { if (!element.hasAttribute('role')) attr(element,'role',value); };

    function recordLayout(table) {
        if (!table.matches('.app-table,.card-table,.user-table,.iv-ledger') || table.closest('.pm-card') || table.parentElement.closest('table')) return;
        const headerRows = table.tHead?.rows;
        if (!headerRows || headerRows.length !== 1) return;
        const headers = [...headerRows[0].cells];
        if (!headers.length || headers.some(cell => cell.colSpan !== 1 || cell.rowSpan !== 1)) return;
        const labels = headers.map(cell => cell.textContent.trim().replace(/\s+/g,' ') || '选择');
        if (!table.classList.contains('ui-record-table')) table.classList.add('ui-record-table');
        if (!table.parentElement.classList.contains('ui-records-region')) table.parentElement.classList.add('ui-records-region');
        role(table,'table');role(table.tHead,'rowgroup');role(headerRows[0],'row');
        headers.forEach(cell => role(cell,'columnheader'));
        [...table.tBodies].forEach(body => {
            role(body,'rowgroup');
            [...body.rows].forEach(row => {
                role(row,'row');
                [...row.cells].forEach((cell,index) => {
                    role(cell,'cell');
                    if (cell.colSpan !== 1 || row.cells.length !== headers.length) return;
                    const label = labels[index];attr(cell,'data-label',label);
                    if (label === '选择') cell.querySelectorAll('input[type="checkbox"]').forEach(input => {
                        if (!input.hasAttribute('aria-label') && !input.labels?.length) attr(input,'aria-label','选择此记录');
                    });
                    if (/操作|确认|审批|处理$/.test(label)) attr(cell,'data-ui-cell','actions');
                    else if (/物料|描述|备注|工作内容|去向|区域|作业计划/.test(label)) attr(cell,'data-ui-cell','wide');
                });
            });
        });
    }
    function panelFor(tab) {
        const declared = tab.getAttribute('aria-controls');
        if (declared) return document.getElementById(declared);
        const key = tab.dataset.tab;
        if (!key) return null;
        const capital = key.charAt(0).toUpperCase() + key.slice(1);
        return ['tab'+capital,'tab-'+key,'ivTab'+capital].map(id => document.getElementById(id)).find(Boolean);
    }
    function syncGroup(group) {
        if (!group.isConnected) { groups.delete(group); return; }
        const buttons = [...group.children].filter(item => item.matches('button,a[href]'));
        if (!buttons.length) return;
        const isTabs = group.matches('.app-tabs') && buttons.every(panelFor);
        if (isTabs) {
            attr(group,'role','tablist');
            if (!group.hasAttribute('aria-label')) attr(group,'aria-label','页面栏目');
            const selected = buttons.find(button => button.classList.contains('active')) || buttons[0];
            const focused = buttons.includes(document.activeElement) ? document.activeElement : selected;
            buttons.forEach(button => {
                const panel = panelFor(button);
                if (!button.id) button.id = 'ui-page-tab-'+(++tabSequence);
                attr(button,'role','tab');attr(button,'aria-selected',button === selected);
                attr(button,'aria-controls',panel.id);attr(button,'tabindex',button === focused ? '0' : '-1');
                role(panel,'tabpanel');attr(panel,'aria-labelledby',button.id);
            });
        } else {
            role(group,buttons.every(button => button.tagName === 'A') ? 'navigation' : 'group');
            if (!group.hasAttribute('aria-label')) attr(group,'aria-label','分类与筛选');
            buttons.forEach(button => {
                const selected = button.classList.contains('active') || button.classList.contains('on');
                if (button.tagName === 'A') {
                    if (selected) attr(button,'aria-current','page');
                    else if (button.getAttribute('aria-current') === 'page') button.removeAttribute('aria-current');
                } else if (group.getAttribute('role') === 'tablist') {
                    if (!group.matches('.pdxf-tabs')) attr(button,'aria-selected',selected);
                }
                else attr(button,'aria-pressed',selected);
            });
        }
        if (!initialized.has(group)) {
            initialized.add(group);
            group.addEventListener('click',() => syncGroup(group));
            group.addEventListener('keydown',event => {
                if (group.getAttribute('role') !== 'tablist' || !['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
                const tabs = [...group.querySelectorAll('[role="tab"]')].filter(tab => !tab.disabled && tab.getClientRects().length);
                const current = tabs.indexOf(document.activeElement);if (current < 0) return;
                event.preventDefault();
                const index = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length-1 : (current + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
                tabs.forEach((tab,n) => attr(tab,'tabindex',n === index ? '0' : '-1'));
                tabs[index].focus();tabs[index].scrollIntoView({block:'nearest',inline:'nearest'});
            });
        }
    }
    function measure() {
        queued = false;
        pendingTables.forEach(recordLayout);pendingTables.clear();
        groups.forEach(syncGroup);
        regions.forEach((hint,region) => {
            if (!region.isConnected) { observer?.unobserve(region);regions.delete(region);hint.remove();return; }
            const overflow = region.clientWidth > 0 && region.scrollWidth > region.clientWidth + 2;
            hint.hidden = !overflow;
            if (region.matches(groupSelector)) return;
            if (overflow) attr(region,'tabindex','0');else region.removeAttribute('tabindex');
        });
    }
    function schedule() { if (!queued) { queued = true;requestAnimationFrame(measure); } }
    const observer = window.ResizeObserver ? new ResizeObserver(schedule) : null;
    function register(region,label,message) {
        if (regions.has(region)) return;
        const hint = document.createElement('div');hint.className = 'ui-scroll-hint';hint.textContent = message;hint.hidden = true;
        region.before(hint);
        if (!region.hasAttribute('aria-label')) attr(region,'aria-label',label);
        role(region,'region');regions.set(region,hint);observer?.observe(region);
    }
    function enhance(root) {
        const iconButtons = root.matches?.('button') ? [root] : [...root.querySelectorAll('button')];
        const iconNames = {close:'关闭',trash:'删除',edit:'编辑',search:'搜索',menu:'打开菜单',plus:'添加',refresh:'刷新',download:'下载',copy:'复制',expand:'展开',collapse:'收起'};
        iconButtons.forEach(button => {
            if (button.textContent.trim() || button.hasAttribute('aria-label') || button.hasAttribute('title')) return;
            const name = button.querySelector('use')?.getAttribute('href')?.replace('#pwa-','');
            if (iconNames[name]) attr(button,'aria-label',iconNames[name]);
        });
        const found = root.matches?.(tables) ? [root] : [...root.querySelectorAll(tables)];
        const containing = root.closest?.('table');
        if (containing?.matches(tables) && !found.includes(containing)) found.push(containing);
        found.forEach(table => {
            let region = table.parentElement;
            if (!region.matches(existingScrollers) && region.style.overflowX !== 'auto') {
                region = document.createElement('div');region.className = 'ui-table-scroll';table.before(region);region.append(table);
            }
            const title = table.caption?.textContent?.trim() || '数据表格';
            register(region,title+'，可左右滚动查看完整内容','左右滑动查看完整表格');pendingTables.add(table);
        });
        const tabGroups = root.matches?.(groupSelector) ? [root] : [...root.querySelectorAll(groupSelector)];
        tabGroups.forEach(group => {
            groups.add(group);syncGroup(group);
            register(group,group.matches('.app-tabs') ? '页面栏目' : '分类与筛选','左右滑动查看更多栏目');
        });
        schedule();
    }
    enhance(document);
    new MutationObserver(records => {
        records.forEach(record => {
            if (record.type === 'attributes') return;
            record.addedNodes.forEach(node => { if (node.nodeType === Node.ELEMENT_NODE) enhance(node); });
        });
        schedule();
    }).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['class','aria-selected']});
    window.addEventListener('resize',schedule,{passive:true});
})();
