/* CCU display numbers unify runtime pages and source Site water records. */
(function (root, factory) {
    if (typeof module === 'object' && module.exports) module.exports = factory();
    else root.IrrigationScope = factory();
})(typeof window !== 'undefined' ? window : this, function () {
    'use strict';
    function number(code) {
        const match = /^CCU(\d+)$/i.exec(code || '');
        return match ? Number(match[1]) : null;
    }
    function sourceNumber(site) {
        return site.number !== null && site.number !== undefined && site.number !== ''
            && Number.isInteger(Number(site.number)) ? Number(site.number) : null;
    }
    function sites(data, code, knownCodes) {
        const rows = data.sites || [];
        if (!code) return rows;
        if (code === 'other') {
            const known = new Set((knownCodes || []).map(number));
            return rows.filter(site => sourceNumber(site) === null || !known.has(sourceNumber(site)));
        }
        const wanted = number(code);
        return rows.filter(site => wanted !== null && sourceNumber(site) === wanted);
    }
    function label(site) {
        const value = sourceNumber(site);
        return (value === null ? '未编号站点' : 'CCU' + value) + (site.name ? ' · ' + site.name : '');
    }
    function pages(tables, water) {
        const result = tables.slice();
        const codes = result.map(t => t.ccu_code);
        if (water.some(data => sites(data, 'other', codes).length)) result.push({
            ccu_code:'other', ccu_name:'其他站点', controllers:[], rows:[],
            col_totals:[], grand_total:null, max_cell:0, total_stations:null
        });
        return result;
    }
    function compactInput(value, isEnd) {
        const compact = (value || '').replace(/[^0-9]/g, '');
        return isEnd && compact.length === 12 ? compact + '00' : compact;
    }
    return {number, sites, label, pages, compactInput};
});
