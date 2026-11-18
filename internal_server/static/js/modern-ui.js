/* Progressive interaction layer. Business handlers, field values and native
   form submission remain owned by each page. No library or network dependency. */
(() => {
    'use strict';
    const fields = 'input, select, textarea';
    const groups = '.ff, .form-group, .pm-field, .jp-field, .crew-field, .wo-field, .op-field, .auth-field, .field, .pd-field, .builder-group, .ctrl-row, .iv-field, .wj-field, .app-grid > div';
    const initialized = new WeakSet();
    const edited = new WeakSet();
    const errors = new WeakMap();
    const flagged = new WeakSet();
    const nativeValidation = window.CSS?.supports('selector(:user-invalid)');
    let sequence = 0;
    let announceTimer;
    let announcedField;
    const announcer = document.createElement('div');
    announcer.className = 'ui-visually-hidden';
    announcer.setAttribute('aria-live', 'polite');
    announcer.setAttribute('aria-atomic', 'true');
    document.body.append(announcer);
    function id(element, prefix) {
        if (!element.id) {
            let value;
            do { value = prefix + (++sequence); } while (document.getElementById(value));
            element.id = value;
        }
        return element.id;
    }
    function labelFor(field) {
        if (field.labels?.length || field.hasAttribute('aria-label') || field.hasAttribute('aria-labelledby')) return;
        const previous = field.previousElementSibling;
        if (previous?.tagName === 'LABEL' && !previous.htmlFor && !previous.querySelector(fields)) {
            previous.htmlFor = id(field, 'ui-field-');
            return;
        }
        const group = field.closest(groups);
        if (!group) return;
        const labels = [...group.querySelectorAll('label, .ctrl-label')].filter(label => label.closest(groups) === group && !label.querySelector(fields));
        if (labels.length !== 1) return;
        const label = labels[0];
        const controls = [...group.querySelectorAll(fields)].filter(control => control.type !== 'hidden' && control.closest(groups) === group);
        if (label.tagName === 'LABEL' && !label.htmlFor && controls[0] === field) label.htmlFor = id(field, 'ui-field-');
        if (!field.labels?.length) field.setAttribute('aria-labelledby', id(label, 'ui-label-'));
    }
    function labelText(field) {
        const label = field.labels?.[0]?.cloneNode(true);
        label?.querySelectorAll('.ui-field-error, [aria-hidden="true"], input, select, textarea').forEach(node => node.remove());
        return label?.textContent.replace(/\s+/g, ' ').trim() || field.getAttribute('aria-label') || (field.getAttribute('aria-labelledby') || '').split(/\s+/).map(value => document.getElementById(value)?.textContent.trim() || '').join(' ');
    }
    function enhanceField(field) {
        if (!field.matches?.(fields) || field.type === 'hidden') return;
        labelFor(field);
        if (initialized.has(field)) return;
        initialized.add(field);
        if (field.willValidate && !field.hasAttribute('aria-invalid')) field.setAttribute('aria-invalid', 'false');
        if (field.tagName === 'SELECT' && !field.multiple && field.size <= 1 && !field.matches('[data-native-select], .select2-hidden-accessible')) field.classList.add('ui-select');
        if (field.tagName === 'TEXTAREA' && !field.style.height && !field.closest('[data-fixed-size], .ai-chat, .ai-chat-panel, .ai-chat-input-area')) field.classList.add('ui-auto-size');
    }
    function message(field) {
        const validity = field.validity;
        if (validity.valueMissing) return field.type === 'checkbox' ? '请勾选此项。' : field.tagName === 'SELECT' ? '请选择一项。' : '请填写此项。';
        if (validity.typeMismatch) return field.type === 'email' ? '请输入有效的邮箱地址，例如 name@example.com。' : '请输入有效的网址。';
        if (validity.rangeUnderflow) return '请输入不小于 ' + field.min + ' 的数值。';
        if (validity.rangeOverflow) return '请输入不大于 ' + field.max + ' 的数值。';
        if (validity.tooShort) return '请至少输入 ' + field.minLength + ' 个字符。';
        if (validity.tooLong) return '请最多输入 ' + field.maxLength + ' 个字符。';
        if (validity.patternMismatch) return field.title || '请按要求填写此项。';
        if (validity.badInput) return '请输入有效的数值。';
        return field.validationMessage;
    }
    function linkError(field, error, shown) {
        const descriptions = (field.getAttribute('aria-describedby') || '').split(/\s+/).filter(value => value && value !== error.id);
        if (shown) descriptions.push(error.id);
        if (descriptions.length) field.setAttribute('aria-describedby', descriptions.join(' '));
        else field.removeAttribute('aria-describedby');
    }
    function clearError(field) {
        const error = errors.get(field);
        if (!flagged.has(field)) return; // Preserve server-supplied aria-invalid.
        field.setAttribute('aria-invalid', 'false');
        field.classList.remove('ui-user-invalid');
        if (error) { error.hidden = true; linkError(field, error, false); }
        flagged.delete(field);
        if (announcedField === field) { clearTimeout(announceTimer); announcer.textContent = ''; }
    }
    function syncError(field, announce = false, attempted = false) {
        if (!field.matches?.(fields) || !field.willValidate) return;
        const invalid = !field.validity.valid && (attempted || (nativeValidation ? field.matches(':user-invalid') : edited.has(field)));
        if (!invalid) { clearError(field); return; }
        let error = errors.get(field);
        if (!error) {
            error = document.createElement('span');
            error.className = 'ui-field-error';
            id(error, 'ui-error-');
            const control = field.closest('.auth-control') || field;
            control.after(error);
            errors.set(field, error);
        }
        const text = '提示：' + message(field);
        const changed = error.hidden || error.textContent !== text;
        error.textContent = text;
        error.hidden = false;
        field.classList.add('ui-user-invalid');
        field.setAttribute('aria-invalid', 'true');
        linkError(field, error, true);
        flagged.add(field);
        if (announce && changed) {
            clearTimeout(announceTimer);
            announcer.textContent = '';
            announcedField = field;
            // A native modal makes the rest of the page inert, including live
            // regions. Move our single announcer into the active dialog.
            (field.closest('dialog') || document.body).append(announcer);
            const label = labelText(field);
            announceTimer = setTimeout(() => {
                if (field.isConnected && flagged.has(field)) announcer.textContent = label + '，' + text;
            }, 500);
        }
    }
    document.addEventListener('input', event => {
        const field = event.target;
        if (!field.matches?.(fields)) return;
        edited.add(field);
        if (field.validity.valid) clearError(field);
    });
    document.addEventListener('blur', event => syncError(event.target, true), true);
    document.addEventListener('change', event => {
        if (!event.target.matches?.(fields)) return;
        edited.add(event.target);
        syncError(event.target, true);
    });
    document.addEventListener('invalid', event => {
        // Reveal required controls in collapsed sections before the browser
        // focuses the first failure. Do not call checkValidity() recursively.
        for (let parent = event.target.parentElement; parent; parent = parent.parentElement) {
            if (parent.tagName === 'DETAILS') parent.open = true;
        }
        syncError(event.target, false, true);
    }, true);
    document.addEventListener('reset', event => {
        setTimeout(() => [...event.target.elements].forEach(field => { edited.delete(field); clearError(field); }));
    }, true);

    /* A native host upgrades existing overlays without replacing their nodes,
       listeners, forms or close/reset routines. Each legacy close path still
       runs; the browser supplies focus containment, Escape and focus return. */
    const overlays = '.app-mask, .modal-overlay, .iv-modal-overlay, .wj-modal-overlay, .fu-modal-overlay, .rm-move-overlay, .iv-create-mask, .fault-modal-overlay, .notif-popup, .lb-overlay, .ann-popup, .v2-modal-container, .v2-sheet-overlay, #importModal, #drawnZonesModal';
    const hosts = new WeakMap();
    function enhanceOverlay(overlay) {
        if (hosts.has(overlay) || overlay.closest('dialog') || !window.HTMLDialogElement?.prototype.showModal) return;
        const host = document.createElement('dialog');
        host.className = 'ui-modal-host';
        host.dataset.uiOverlay = overlay.id || '';
        const split = overlay.classList.contains('v2-modal-container');
        if (split) host.dataset.uiSplitModal = '';
        const title = overlay.querySelector('h2, h3, [id$="Title"], .notif-badge, .ann-badge');
        if (title) host.setAttribute('aria-labelledby', id(title, 'ui-dialog-title-'));
        else host.setAttribute('aria-label', overlay.getAttribute('aria-label') || (overlay.classList.contains('lb-overlay') ? '图片预览' : '操作窗口'));
        // Move semantics from a legacy ARIA dialog to its native host.
        if (overlay.getAttribute('role') === 'dialog') overlay.removeAttribute('role');
        overlay.removeAttribute('aria-modal');
        overlay.querySelectorAll('[role="dialog"]').forEach(panel => {
            panel.removeAttribute('role');
            panel.removeAttribute('aria-modal');
        });
        overlay.querySelectorAll('button').forEach(button => {
            if (/^[×✕✖]$/.test(button.textContent.trim()) && !button.hasAttribute('aria-label')) button.setAttribute('aria-label', '关闭弹窗');
        });
        overlay.before(host);
        host.append(overlay);
        hosts.set(overlay, host);
        const locked = overlay.classList.contains('ann-popup');
        if (locked) {
            host.setAttribute('closedby', 'none');
            host.addEventListener('cancel', event => event.preventDefault());
        }
        const visible = () => !overlay.hidden && getComputedStyle(overlay).display !== 'none' && getComputedStyle(overlay).visibility !== 'hidden';
        const sync = () => {
            if (visible() && !host.open && host.isConnected) {
                // Label freshly rendered fields before the native dialog moves
                // focus, so the first screen-reader announcement has a name.
                overlay.querySelectorAll(fields).forEach(enhanceField);
                host.showModal();
            }
            else if (!visible() && host.open) host.close();
        };
        host.addEventListener('close', () => {
            host.returnValue = '';
            if (!host.isConnected || !host.contains(overlay) || !visible()) return;
            // Use existing close actions, which also clean selection and form
            // state. Never synthesize a submit or acknowledge a notification.
            const close = overlay.querySelector('[data-ui-close], .notif-x, .lb-close, .fu-modal-close, .iv-modal-close, .wj-modal-close, .app-dlg-close, .modal-close, .v2-modal-close, button[aria-label^="关闭"], button[onclick*="close" i]');
            if (close) close.click();
            else if (split) document.getElementById(overlay.id.replace('Container', 'Backdrop'))?.click();
            else overlay.click();
            if (visible()) {
                overlay.classList.remove('open', 'show', 'visible', 'active');
                if (visible()) overlay.style.display = 'none';
            }
        });
        if (split) host.addEventListener('click', event => {
            if (event.target === host) document.getElementById(overlay.id.replace('Container', 'Backdrop'))?.click();
        });
        const visibilityObserver = new MutationObserver(sync);
        visibilityObserver.observe(overlay, {attributes: true, attributeFilter: ['class', 'style', 'hidden']});
        const removalObserver = new MutationObserver(() => {
            if (host.contains(overlay)) return;
            // Dynamic pickers are moved/rebuilt by their owning page. A removed
            // picker must never leave an empty modal blocking the application.
            visibilityObserver.disconnect();
            removalObserver.disconnect();
            hosts.delete(overlay);
            if (host.open) host.close();
            host.remove();
        });
        removalObserver.observe(host, {childList: true});
        sync();
    }
    const disclosureSelector = '.settings-card-header[onclick], .zone-section-header[onclick], .section-title.collapsible[onclick], .drill-head[onclick], .region-header[onclick], .patch-header[onclick], .wr-expand-hint';
    const disclosures = new WeakSet();
    function enhanceDisclosure(header) {
        if (disclosures.has(header) || header.matches('button, summary')) return;
        disclosures.add(header);
        const card = header.classList.contains('wr-expand-hint') ? header.closest('.wr-card') : null;
        const panel = card ? card.querySelector('.wr-detail') : header.nextElementSibling;
        if (!panel) return;
        const button = document.createElement('button');
        button.type = 'button';
        button.className = card ? 'wr-expand-hint ui-card-toggle' : 'ui-section-toggle';
        button.setAttribute('aria-controls', id(panel, 'ui-panel-'));
        if (card) header.replaceWith(button);
        else {
            const title = header.querySelector(':scope > h2, :scope > h3') || header;
            // Keep export links and other independent actions outside the
            // disclosure button, rather than nesting interactive elements.
            [...title.childNodes].filter(node => !node.matches?.('a, button, .header-actions')).forEach(node => button.append(node));
            title.prepend(button);
        }
        const sync = () => {
            const expanded = !panel.hidden && getComputedStyle(panel).display !== 'none';
            button.setAttribute('aria-expanded', String(expanded));
            if (card) button.textContent = expanded ? '收起详情' : '展开详情';
        };
        button.addEventListener('click', event => {
            event.stopPropagation();
            (card ? card.querySelector('.wr-summary') : header).click();
            sync();
        });
        const observer = new MutationObserver(sync);
        for (const node of new Set([panel, card || header, header.parentElement].filter(Boolean))) observer.observe(node, {attributes: true, attributeFilter: ['class', 'style', 'hidden']});
        sync();
    }
    const actions = '.pm-switch[onclick], .zd-switch[onclick], .iv-switch[onclick], .wr-thumb-wrap[onclick], .wr-photo-wrap[onclick], .wq-photo-thumb[onclick], .zd-photo-thumb[onclick]';
    const actionControls = new WeakSet();
    function enhanceAction(control) {
        if (actionControls.has(control)) return;
        actionControls.add(control);
        const isSwitch = control.matches('.pm-switch, .zd-switch, .iv-switch');
        control.setAttribute('role', isSwitch ? 'switch' : 'button');
        if (control.matches('.iv-switch')) control.setAttribute('aria-label', '确认库存流水，' + (control.title || '开启后扣减库存并计入统计'));
        if (!isSwitch) control.setAttribute('aria-label', control.querySelector('video') ? '播放现场视频' : '查看现场照片');
        const sync = () => {
            const disabled = control.classList.contains('disabled');
            control.tabIndex = disabled ? -1 : 0;
            if (isSwitch) {
                control.setAttribute('aria-checked', String(!!control.querySelector('.pm-switch-track.on, .zd-switch-track.on, .iv-switch-track.on')));
                control.setAttribute('aria-disabled', String(disabled));
            }
        };
        control.addEventListener('keydown', event => {
            if (event.target !== control || event.isComposing || !['Enter', ' '].includes(event.key)) return;
            event.preventDefault();
            if (!control.classList.contains('disabled') && !event.repeat) control.click();
        });
        if (isSwitch) new MutationObserver(sync).observe(control, {attributes: true, subtree: true, attributeFilter: ['class']});
        sync();
    }
    function enhance(root) {
        if (root.matches?.(fields)) enhanceField(root);
        root.querySelectorAll(fields).forEach(enhanceField);
        if (root.matches?.(overlays)) enhanceOverlay(root);
        root.querySelectorAll(overlays).forEach(enhanceOverlay);
        if (root.matches?.(disclosureSelector)) enhanceDisclosure(root);
        root.querySelectorAll(disclosureSelector).forEach(enhanceDisclosure);
        if (root.matches?.(actions)) enhanceAction(root);
        root.querySelectorAll(actions).forEach(enhanceAction);
    }
    const main = document.querySelector('main, .dashboard-container, .app-wrap, .form-container, .settings-container, .sh-container, .irrig-container, .cr-container, .profile-container, .register-container, .approval-container, .crew-wrap, .jp-wrap, .pm-wrap, .zone-editor-container, .wo-wrap, .zd-wrap');
    if (main) {
        const skip = document.createElement('a');
        skip.className = 'ui-skip-link';
        skip.href = '#' + id(main, 'ui-main-');
        skip.textContent = '跳到主要内容';
        if (!main.hasAttribute('tabindex')) main.tabIndex = -1;
        document.body.prepend(skip);
    }
    enhance(document);
    const pending = new Set();
    let queued = false;
    new MutationObserver(records => {
        records.forEach(record => record.addedNodes.forEach(node => {
            if (node.nodeType === Node.ELEMENT_NODE && node.namespaceURI === 'http://www.w3.org/1999/xhtml') pending.add(node);
        }));
        if (!pending.size || queued) return;
        queued = true;
        requestAnimationFrame(() => {
            queued = false;
            pending.forEach(node => { if (node.isConnected) enhance(node); });
            pending.clear();
        });
    }).observe(document.body, {childList: true, subtree: true});
})();
