/* Reuse the map's history entry for uninterrupted bottom-tab navigation.
 * Stores navigation metadata only; the browser owns the in-memory page cache. */
(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    else api.start(root, root.document);
})(typeof window !== 'undefined' ? window : this, function () {
    'use strict';
    const KEY = 'irrigation-tab-navigation-v1';
    const STATE = 'irrigationTab';
    function create(win, uid, referrer) {
        let storage;
        try { storage = win.sessionStorage; storage.setItem(KEY + '-test', '1'); storage.removeItem(KEY + '-test'); }
        catch (_) { return null; }
        const read = () => { try { return JSON.parse(storage.getItem(KEY)); } catch (_) { return null; } };
        const write = value => { try { storage.setItem(KEY, JSON.stringify(value)); } catch (_) {} };
        const url = () => win.location.href;
        const isMap = () => { const value = new URL(url()); return value.pathname === '/' && !value.search; };
        const epoch = () => Date.now().toString(36) + '-' + Math.random().toString(36).slice(2);
        let entry = win.history.state?.[STATE];
        let record = read();
        function reset() {
            entry = {uid, epoch:epoch(), index:0};
            record = {uid, epoch:entry.epoch};
            const previous = typeof win.history.state === 'object' ? win.history.state : {};
            win.history.replaceState({...previous, [STATE]:entry}, '');
        }
        if (!record || record.uid !== uid || !entry || entry.uid !== uid || entry.epoch !== record.epoch || !Number.isInteger(entry.index)) {
            const pending = record?.pending;
            if (record?.uid === uid && pending?.url === url() && pending.from === referrer && Date.now() - pending.time < 60000 && Number.isInteger(pending.index)) {
                entry = {uid, epoch:record.epoch, index:pending.index};
                win.history.replaceState({...win.history.state, [STATE]:entry}, '');
            } else reset();
        }
        function saveCurrent() {
            record.current = entry.index;
            delete record.pending;
            if (isMap()) record.mapIndex = entry.index;
            write(record);
        }
        saveCurrent();
        return {
            navigate(target) {
                const next = new URL(target, url());
                if (next.origin !== new URL(url()).origin) return false;
                if (next.href === url()) return true; // Tapping the active tab is a no-op.
                const latest = read();
                if (!latest || latest.uid !== uid || latest.epoch !== entry.epoch) return false;
                const distance = entry.index - latest.mapIndex;
                if (next.pathname === '/' && !next.search && Number.isInteger(latest.mapIndex) && distance > 0 && distance < win.history.length) {
                    win.history.go(-distance);
                    return true;
                }
                latest.pending = {url:next.href, from:url(), index:entry.index + 1, time:Date.now()};
                write(latest);
                return false; // Normal navigation retains server auth and form behavior.
            },
            resume() {
                record = read();
                if (record && record.uid !== uid) { win.location.reload(); return; }
                if (!record || record.epoch !== entry.epoch) reset();
                saveCurrent();
            }
        };
    }
    function start(win, doc) {
        const nav = doc.querySelector('.pwa-bottom-nav[data-user-id]');
        if (!nav) {
            // Offline help has no authenticated shell, but must not be mistaken
            // for logging out when a connection fails during navigation.
            if (/^\/(login|register)\/$/.test(win.location.pathname)) {
                try { win.sessionStorage.setItem(KEY, JSON.stringify({uid:''})); } catch (_) {}
            }
            return;
        }
        const controller = create(win, nav.dataset.userId, doc.referrer);
        if (!controller) return;
        nav.querySelectorAll('a[data-pwa-nav]').forEach(link => link.addEventListener('click', event => {
            if (event.defaultPrevented || event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
            if (controller.navigate(link.href)) event.preventDefault();
        }));
        win.addEventListener('pageshow', event => { if (event.persisted) controller.resume(); });
    }
    return {create, start};
});
