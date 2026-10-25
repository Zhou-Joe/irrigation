/* Streaming protocol and response state, shared by the UI and regression tests. */
(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.AIChatCore = api;
})(typeof window !== 'undefined' ? window : this, function () {
    'use strict';
    const labels = {
        query_work_reports:'查询维修记录', query_work_report_stats:'汇总维修记录', query_work_entries_stats:'分析工作内容',
        query_pending_repairs:'查询待修工单', query_difficult_workorders:'查询疑难工单', query_water_requests:'查询用水需求',
        query_projects:'查询项目', query_zones:'查询区域', query_weather:'查询天气', query_irrigation_overview:'查询灌溉概况',
        query_irrigation_runtime:'分析灌溉运行', query_flow_daily:'分析每日流量', query_pm_dispatch:'查询 PM 任务',
        query_pm_plans:'查询 PM 计划', query_inventory:'查询库存', query_inventory_transactions:'查询库存流水',
        query_purchase_orders:'查询采购订单', query_crews_workers:'查询班组人员', query_geo_assets:'查询地理设备',
        generate_weekly_report:'生成周报', get_weekly_report_material:'准备周报数据', build_weekly_report:'编排周报',
        export_work_reports_excel:'导出维修报表', send_report_email:'发送报表邮件', run_python_code:'分析数据与生成文件'
    };
    function toolLabel(name) { return labels[name] || String(name || '工具').replace(/[_-]/g,' ').slice(0,80); }
    function formatBytes(value) {
        if (!Number.isFinite(value) || value < 0) return '';
        if (value < 1024) return value + ' B';
        if (value < 1048576) return (value/1024).toFixed(1) + ' KB';
        return (value/1048576).toFixed(1) + ' MB';
    }
    function safeLink(raw, origin) {
        if (typeof raw !== 'string' || !raw.trim()) return null;
        try {
            const url = new URL(raw, origin);
            return ['https:','http:'].includes(url.protocol) && !url.username && !url.password ? url : null;
        } catch (_) { return null; }
    }
    function artifactInfo(file, origin) {
        if (!file || typeof file.url !== 'string') return null;
        const url = safeLink(file.url, origin);
        if (!url || url.origin !== new URL(origin).origin) return null;
        let parts;
        try { parts = decodeURIComponent(url.pathname).split('/').filter(Boolean); } catch (_) { return null; }
        if (parts.length !== 4 || !((parts[0] === 'ai' && parts[1] === 'files') || (parts[0] === 'media' && parts[1] === 'ai_workspaces')) || !/^u\d+-[0-9a-f]{8,32}$/.test(parts[2]) || parts[3].startsWith('.') || /[\\/]/.test(parts[3])) return null;
        const name = String(file.name || parts[3]).slice(0,240);
        const ext = parts[3].split('.').pop().toLowerCase();
        const kind = /^(png|jpe?g|webp|gif|avif)$/.test(ext) ? 'image' : /^(xlsx?|csv)$/.test(ext) ? 'spreadsheet' : ext === 'pdf' ? 'pdf' : /^(docx?|txt|md)$/.test(ext) ? 'document' : 'file';
        return {name, url:url.href, kind, type:ext.toUpperCase(), size:formatBytes(file.size)};
    }
    function createParser(onEvent) {
        let buffer = '';
        function frame(text) {
            const data = text.split(/\r\n|\n|\r/).filter(line => line.startsWith('data:')).map(line => line.slice(5).replace(/^ /,'')).join('\n');
            if (!data || data === '[DONE]') return;
            let event;
            try { event = JSON.parse(data); } catch (_) { throw new Error('回复数据不完整，请重新编辑请求后发送。'); }
            if (event && typeof event.event === 'string') onEvent(event);
        }
        return {
            push(text) {
                buffer += text;
                const frames = buffer.split(/\r\n\r\n|\n\n|\r\r/);
                buffer = frames.pop(); frames.forEach(frame);
            },
            finish(text = '') { this.push(text); if (buffer.trim()) frame(buffer); buffer = ''; }
        };
    }
    function createTurn(now = Date.now()) {
        return {phase:'preparing', text:'', tools:[], files:[], error:'', started:now, ended:null};
    }
    function applyEvent(turn, event, now = Date.now()) {
        if (turn.ended !== null) return;
        if (event.event === 'token') {
            turn.text += String(event.text || ''); turn.phase = 'writing';
        } else if (event.event === 'tool_start') {
            let tool = event.id && turn.tools.find(item => item.id === event.id);
            if (!tool) {
                tool = {id:event.id || 'local-' + turn.tools.length, name:String(event.name || 'tool'), status:'running', started:now, ended:null, args:event.args || {}, output:''};
                turn.tools.push(tool);
            }
            turn.phase = 'tool';
        } else if (event.event === 'tool_end') {
            let tool = event.id && turn.tools.find(item => item.id === event.id);
            if (!tool) tool = turn.tools.find(item => item.name === event.name && item.status === 'running');
            if (!tool) {
                tool = {id:event.id || 'local-' + turn.tools.length, name:String(event.name || 'tool'), started:now, args:{}};
                turn.tools.push(tool);
            }
            tool.output = typeof event.output === 'string' ? event.output : JSON.stringify(event.output || '');
            let parsed;
            try { parsed = JSON.parse(tool.output); } catch (_) {}
            const failed = event.status === 'error' || (parsed && typeof parsed === 'object' && (parsed.error || parsed.success === false || parsed.exit_code > 0));
            tool.status = failed ? 'error' : 'done'; tool.ended = now;
            turn.phase = turn.tools.some(item => item.status === 'running') ? 'tool' : 'thinking';
        } else if (event.event === 'file') {
            if (!turn.files.some(file => file.url === event.url)) turn.files.push({...event});
        } else if (event.event === 'error') {
            finishTurn(turn, 'error', String(event.message || '本次回复未完成。'), now);
        } else if (event.event === 'done') {
            finishTurn(turn, 'done', '', now);
        }
    }
    function finishTurn(turn, phase, message = '', now = Date.now()) {
        if (turn.ended !== null) return;
        turn.phase = phase; turn.ended = now; turn.error = message;
        turn.tools.forEach(tool => { if (tool.status === 'running') { tool.status = 'interrupted'; tool.ended = now; } });
        if (phase === 'done' && !turn.text.trim() && !turn.files.length) {
            turn.phase = 'error'; turn.error = '本次未返回内容，请重新编辑请求后发送。';
        }
    }
    return {toolLabel, formatBytes, safeLink, artifactInfo, createParser, createTurn, applyEvent, finishTurn};
});
