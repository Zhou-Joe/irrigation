/* The same local SVG symbol set powers the workbench and map controls. */
(function () {
    'use strict';
    window.uiIcon = function (name) {
        if (typeof name !== 'string' || !/^[a-z][a-z0-9-]*$/.test(name)) return '';
        return '<svg class="ui-icon" aria-hidden="true" focusable="false"><use href="#pwa-' + name + '"></use></svg>';
    };
})();
