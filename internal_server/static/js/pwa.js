(function () {
    'use strict';
    var installEvent = null, registration = null, dirty = false, reloadAfterUpdate = false;
    var launcher = document.getElementById('pwaLauncher');
    var installDialog = document.getElementById('pwaInstall');
    var toastTimer;
    function warnBeforeLeave(event) { event.preventDefault(); event.returnValue = ''; }
    function setDirty(value) {
        if (dirty === value) return;
        dirty = value;
        if (dirty) window.addEventListener('beforeunload', warnBeforeLeave);
        else window.removeEventListener('beforeunload', warnBeforeLeave);
    }
    function toast(message) {
        var el = document.getElementById('pwaToast');
        el.textContent = message; el.hidden = false;
        clearTimeout(toastTimer); toastTimer = setTimeout(function () { el.hidden = true; }, 6000);
    }
    function setShellStatus(message) {
        var el = document.getElementById('pwaShellStatus');
        if (el) el.textContent = message;
    }
    function installed() {
        return window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
    }
    function showDialog(dialog) {
        if (!dialog) return;
        if (launcher && launcher.open) launcher.close();
        dialog.showModal();
    }
    function openLauncher() {
        if (!launcher) return;
        if (launcher.open) { launcher.close(); return; }
        var search = document.getElementById('pwaModuleSearch');
        search.value = ''; filterModules(''); showDialog(launcher);
        // Keep the software keyboard closed until the worker chooses search.
        launcher.querySelector('[data-pwa-close]').focus();
    }
    function filterModules(query) {
        var found = 0;
        launcher.querySelectorAll('.pwa-module').forEach(function (link) {
            link.hidden = link.textContent.toLowerCase().indexOf(query.toLowerCase().trim()) < 0;
            if (!link.hidden) found++;
        });
        document.getElementById('pwaNoModules').hidden = found > 0;
    }
    function canSubmit() {
        if (navigator.onLine) return true;
        toast('当前离线，尚未提交。请保持此页面，恢复网络后再试。');
        return false;
    }
    window.IrrigationPWA = {openLauncher: openLauncher, canSubmit: canSubmit,
        markClean: function () { setDirty(false); }, markDirty: function () { setDirty(true); }};
    // The native dialog supersedes the old CSS-only dropdown; remove its
    // off-screen links from keyboard focus and accessibility navigation.
    ['mobileNavDropdown', 'mobileNavOverlay'].forEach(function (id) {
        var element = document.getElementById(id); if (element) element.hidden = true;
    });
    document.querySelectorAll('[data-pwa-launcher]').forEach(function (button) { button.addEventListener('click', openLauncher); });
    document.querySelectorAll('[data-pwa-close]').forEach(function (button) {
        button.addEventListener('click', function () { button.closest('dialog').close(); });
    });
    document.querySelectorAll('.pwa-dialog').forEach(function (dialog) {
        dialog.addEventListener('click', function (event) {
            var bounds = dialog.getBoundingClientRect();
            if (event.target === dialog && (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom)) dialog.close();
        });
    });
    if (launcher) document.getElementById('pwaModuleSearch').addEventListener('input', function (event) { filterModules(event.target.value); });
    var pathname = window.location.pathname;
    var active = pathname === '/app/' ? 'home' : pathname === '/' ? 'map' : pathname.indexOf('/work-reports/') === 0 ? 'work' : pathname.indexOf('/inventory/') === 0 ? 'stock' : null;
    document.querySelectorAll('[data-pwa-nav]').forEach(function (link) {
        if (link.dataset.pwaNav === active) link.setAttribute('aria-current', 'page');
    });
    if (!active) document.querySelectorAll('.pwa-bottom-nav [data-pwa-launcher]').forEach(function (button) { button.setAttribute('aria-current', 'page'); });
    function connectionChanged() {
        document.getElementById('pwaConnection').hidden = navigator.onLine;
        document.documentElement.classList.toggle('pwa-is-offline', !navigator.onLine);
    }
    window.addEventListener('offline', connectionChanged);
    window.addEventListener('online', function () { connectionChanged(); toast('网络连接已恢复。请核对记录后继续提交。'); });
    connectionChanged();
    // Leave data on screen on connection loss. Never auto-replay a mutation:
    // its response may have been lost after the server already accepted it.
    function trackEdits(event) {
        var form = event.target.closest('form');
        if (!form || form.id === 'pwaModuleSearch') return;
        var method = (form.getAttribute('method') || 'get').toLowerCase();
        if (method === 'post' || /^(wo|wr|inv)ModalForm$/.test(form.id)) setDirty(true);
    }
    document.addEventListener('input', trackEdits);
    document.addEventListener('change', trackEdits);
    document.addEventListener('submit', function (event) {
        var method = (event.target.getAttribute('method') || 'get').toLowerCase();
        if (method !== 'get' && !canSubmit()) { event.preventDefault(); event.stopImmediatePropagation(); return; }
        setDirty(false);
    }, true);
    document.addEventListener('pwa:submitted', function () { setDirty(false); });
    function installHelp() {
        var instructions = document.getElementById('pwaInstallInstructions');
        var button = document.getElementById('pwaNativeInstall');
        button.hidden = !installEvent;
        if (installed()) instructions.innerHTML = '<p>当前已在应用模式中打开。你可以直接从手机桌面的「灌溉管理」图标进入。</p>';
        else if (!window.isSecureContext) instructions.innerHTML = '<p>请通过网站的 HTTPS 地址打开，再添加到手机桌面。</p>';
        else if (/iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)) {
            instructions.innerHTML = '<ol><li>打开浏览器的「分享」菜单。</li><li>选择「添加到主屏幕」，确认名称后点「添加」。</li><li>从桌面图标进入工作台。</li></ol><p>如果没有此选项，请用 Safari 打开网站后重试。</p>';
        } else if (installEvent) instructions.innerHTML = '<p>点击下方「安装应用」，按手机提示确认安装即可。</p>';
        else instructions.innerHTML = '<ol><li>打开浏览器菜单（⋮ 或 …）。</li><li>选择「安装应用」或「添加到主屏幕」。</li><li>确认后，从桌面图标打开。</li></ol><p>如果当前浏览器没有安装选项，请使用 Chrome 或 Edge 打开此网站。</p>';
        showDialog(installDialog);
    }
    document.querySelectorAll('[data-pwa-install]').forEach(function (button) { button.addEventListener('click', installHelp); });
    window.addEventListener('beforeinstallprompt', function (event) {
        event.preventDefault(); installEvent = event;
        if (installDialog.open) { document.getElementById('pwaNativeInstall').hidden = false; }
    });
    document.getElementById('pwaNativeInstall').addEventListener('click', async function () {
        if (!installEvent) return;
        var prompt = installEvent; installEvent = null;
        this.hidden = true;
        await prompt.prompt();
        var choice = await prompt.userChoice;
        if (choice.outcome === 'accepted') installDialog.close();
    });
    window.addEventListener('appinstalled', function () { installEvent = null; installDialog.close(); toast('安装完成，可从桌面打开工作台。'); });
    if (installed()) {
        document.documentElement.classList.add('pwa-standalone');
        var installCard = document.querySelector('.field-install');
        if (installCard) installCard.hidden = true;
    }
    function offerUpdate() {
        document.getElementById('pwaUpdate').hidden = !(registration && registration.waiting && navigator.serviceWorker.controller);
    }
    if ('serviceWorker' in navigator && window.isSecureContext) {
        navigator.serviceWorker.register('/service-worker.js', {scope: '/', updateViaCache: 'none'}).then(function (reg) {
            registration = reg; offerUpdate();
            navigator.serviceWorker.ready.then(function () {
                setShellStatus('离线提示已就绪。工单、照片和业务数据仍需联网提交。');
            });
            reg.addEventListener('updatefound', function () {
                var worker = reg.installing;
                if (worker) worker.addEventListener('statechange', function () {
                    if (worker.state === 'installed') offerUpdate();
                    if (worker.state === 'redundant' && !navigator.serviceWorker.controller)
                        setShellStatus('离线提示未准备完成，请保持网络连接，稍后重新打开应用。');
                });
            });
        }).catch(function () {
            // Site stays functional if storage or service workers are restricted.
            document.documentElement.classList.add('pwa-shell-unavailable');
            setShellStatus('当前浏览器无法启用离线提示，请保持网络连接。');
        });
        navigator.serviceWorker.addEventListener('controllerchange', function () {
            offerUpdate();
            if (reloadAfterUpdate) { reloadAfterUpdate = false; window.location.reload(); }
        });
        // Recheck on return from a shift break without a polling timer.
        document.addEventListener('visibilitychange', function () {
            if (!document.hidden && registration && navigator.onLine) registration.update().catch(function () {});
        });
    } else setShellStatus('当前环境不支持离线提示。请通过 HTTPS 在手机浏览器中打开。');
    document.getElementById('pwaUpdateBtn').addEventListener('click', function () {
        if (!registration || !registration.waiting) { offerUpdate();return; }
        if (window._woInflight) { toast('工单正在提交，请等待结果后再更新。'); return; }
        if (dirty && !window.confirm('有尚未提交的内容或照片，更新会关闭当前页面。确认放弃并更新？')) return;
        setDirty(false); reloadAfterUpdate = true; registration.waiting.postMessage({type: 'ACTIVATE_UPDATE'});
    });
}());
