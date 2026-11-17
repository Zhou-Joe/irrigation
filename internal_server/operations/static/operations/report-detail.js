/* Delegated handlers also work after status and comment fragments refresh. */
(function () {
    'use strict';
    const initialized = new WeakSet();
    function clear(viewer) {
        const video = viewer.querySelector('[data-media-video]');
        video.pause(); video.removeAttribute('src'); video.load();
        viewer.querySelector('[data-media-image]').removeAttribute('src');
    }
    function show(viewer, index) {
        const items = [...viewer.closest('.pest-detail').querySelectorAll('[data-pest-media]')];
        if (!items.length) return;
        index = (index + items.length) % items.length; viewer.dataset.index = String(index);
        clear(viewer);
        const item = items[index], isVideo = item.dataset.video === 'true';
        const image = viewer.querySelector('[data-media-image]'), video = viewer.querySelector('[data-media-video]');
        image.hidden = isVideo; video.hidden = !isVideo;
        if (isVideo) video.src = item.href;
        else { image.src = item.href; image.alt = item.querySelector('img')?.alt || '现场图片'; }
        viewer.querySelector('[data-media-counter]').textContent = (index + 1) + ' / ' + items.length;
        viewer.querySelector('[data-media-original]').href = item.href;
        viewer.querySelectorAll('[data-media-step]').forEach(button => button.disabled = items.length < 2);
        if (!initialized.has(viewer)) { viewer.addEventListener('close', () => clear(viewer)); initialized.add(viewer); }
        if (!viewer.open) viewer.showModal();
    }
    document.addEventListener('click', event => {
        const item = event.target.closest('[data-pest-media]');
        if (item && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) {
            const viewer = item.closest('.pest-detail')?.querySelector('.pest-media-viewer');
            if (!viewer?.showModal) return;
            event.preventDefault(); show(viewer, [...item.closest('.pest-detail').querySelectorAll('[data-pest-media]')].indexOf(item)); return;
        }
        const viewer = event.target.closest('.pest-media-viewer'); if (!viewer) return;
        if (event.target === viewer || event.target.closest('[data-media-close]')) viewer.close();
        const step = event.target.closest('[data-media-step]');
        if (step) show(viewer, Number(viewer.dataset.index || 0) + Number(step.dataset.mediaStep));
    });
    document.addEventListener('keydown', event => {
        const viewer = document.querySelector('.pest-media-viewer[open]');
        if (!viewer || !['ArrowLeft', 'ArrowRight'].includes(event.key) || event.target.tagName === 'VIDEO') return;
        event.preventDefault(); show(viewer, Number(viewer.dataset.index || 0) + (event.key === 'ArrowLeft' ? -1 : 1));
    });
})();
