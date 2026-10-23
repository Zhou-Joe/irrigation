/* Progressive enhancement for data-heavy web pages. No application state or
   form values are changed; wide tables retain their native table semantics. */
(() => {
    'use strict';
    const tables = 'table.app-table,table.user-table,table.card-table,table.zone-table,table.zd-table,table.cr-data-table,table.iv-price-table,table.stats-table,table.params,table.rest';
    const existingScrollers = '.app-table-wrap,.zone-table-container,.ui-table-scroll';
    const regions = new Map();
    let queued = false;
    function measure() {
        queued = false;
        regions.forEach((hint, region) => {
            if (!region.isConnected) { observer?.unobserve(region); regions.delete(region); hint.remove(); return; }
            const overflow = region.clientWidth > 0 && region.scrollWidth > region.clientWidth + 2;
            hint.hidden = !overflow;
            if (overflow) region.setAttribute('tabindex', '0');
            else region.removeAttribute('tabindex');
        });
    }
    function schedule() { if (!queued) { queued = true; requestAnimationFrame(measure); } }
    const observer = window.ResizeObserver ? new ResizeObserver(schedule) : null;
    function register(region, label, message) {
        if (regions.has(region)) return;
        const hint = document.createElement('div');
        hint.className = 'ui-scroll-hint';
        hint.textContent = message;
        hint.hidden = true;
        region.before(hint);
        region.setAttribute('aria-label', label);
        region.setAttribute('role', 'region');
        regions.set(region, hint);
        observer?.observe(region);
    }
    function enhance(root) {
        const found = root.matches?.(tables) ? [root] : [...root.querySelectorAll(tables)];
        found.forEach(table => {
            let region = table.parentElement;
            if (!region.matches(existingScrollers)) {
                region = document.createElement('div');
                region.className = 'ui-table-scroll';
                table.before(region);
                region.append(table);
            }
            const title = table.caption?.textContent?.trim() || '数据表格';
            register(region, title + '，可左右滚动查看完整内容', '↔ 左右滑动查看完整表格');
        });
        const tabs = root.matches?.('.app-tabs,.pm-subtabs') ? [root] : [...root.querySelectorAll('.app-tabs,.pm-subtabs')];
        tabs.forEach(region => register(region,
            region.matches('.pm-subtabs') ? '计划分类，可左右滚动' : '栏目导航，可左右滚动',
            region.matches('.pm-subtabs') ? '↔ 左右滑动查看计划分类' : '↔ 左右滑动切换栏目'));
        schedule();
    }
    enhance(document);
    new MutationObserver(records => {
        records.forEach(record => record.addedNodes.forEach(node => {
            if (node.nodeType === Node.ELEMENT_NODE) enhance(node);
        }));
        schedule();
    }).observe(document.body, { childList:true, subtree:true });
    window.addEventListener('resize', schedule, { passive:true });
})();
