/* Shared between the irrigation dashboard and its per-account display controls. */
window.IrrigationPipelineDisplay = (() => {
    const key = user => 'irrigation.pipeline-display.' + user;
    function read(user) {
        try {
            const values = JSON.parse(localStorage.getItem(key(user))) || {};
            return typeof values === 'object' && !Array.isArray(values) ? values : {};
        } catch { return {}; }
    }
    function enabled(values, option) {
        if (typeof values[option] === 'boolean') return values[option];
        return option !== 'cad_reference' && option !== 'cad_notes';
    }
    const panel = document.querySelector('[data-pipeline-display-settings]');
    if (panel) {
        const user = panel.dataset.pipelineDisplayUser;
        const fields = panel.querySelectorAll('[data-pipe-option]');
        const status = panel.querySelector('[data-pipe-status]');
        function sync() {
            const values = read(user);
            for (const field of fields) field.checked = enabled(values, field.dataset.pipeOption);
        }
        panel.addEventListener('change', event => {
            const field = event.target;
            if (!field.matches('[data-pipe-option]')) return;
            const values = read(user);
            values[field.dataset.pipeOption] = field.checked;
            try {
                localStorage.setItem(key(user), JSON.stringify(values));
                status.hidden = true;
            } catch {
                sync();
                status.textContent = '浏览器无法保存图层设置。';
                status.hidden = false;
            }
        });
        window.addEventListener('pageshow', sync);
        window.addEventListener('storage', event => { if (!event.key || event.key === key(user)) sync(); });
        const icons = window.IrrigationValveIcons;
        icons.configure(JSON.parse(document.getElementById('map-valve-shapes').textContent));
        icons.legend(panel.querySelector('[data-valve-legend]'));
        panel.querySelector('[data-valve-detail-zoom]').textContent = icons.detailZoom;
        sync();
    }
    return {read, enabled, key};
})();
