(function () {
    'use strict';
    const MAX_FILE = 50 * 1024 * 1024, MAX_TOTAL = 100 * 1024 * 1024;
    const IMAGE = /\.(?:jpe?g|png|webp|gif|bmp)$/i, VIDEO = /\.(?:mp4|mov|m4v|webm)$/i;
    function validate(files, retained = 0) {
        if (files.length + retained > 10) return '每张工单最多保留 10 个图片或视频附件。';
        if (files.some(file => !IMAGE.test(file.name) && !VIDEO.test(file.name))) return '请选择支持的图片或视频格式。';
        if (files.some(file => !file.size || file.size > MAX_FILE)) return '附件不能为空，单个附件不能超过 50 MB。';
        if (files.reduce((sum, file) => sum + file.size, 0) > MAX_TOTAL) return '本次上传的附件总大小不能超过 100 MB。';
        return '';
    }
    function mount(form, onChange = () => {}) {
        const input = form.querySelector('#pestReportMedia'), camera = form.querySelector('#pestMediaCameraInput'), previews = form.querySelector('#pestMediaPreviews'), status = form.querySelector('#pestMediaStatus');
        if (!input || !previews || !status) return {destroy() {}};
        let urls = [], files = Array.from(input.files || []);
        const galleryButton = form.querySelector('#pestMediaAdd'), cameraButton = form.querySelector('#pestMediaCamera');
        const retained = () => form.querySelectorAll('[name="media_remove"]:not(:checked)').length;
        const icon = name => { const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'), use = document.createElementNS(svg.namespaceURI, 'use'); svg.classList.add('ui-icon'); svg.setAttribute('aria-hidden', 'true'); use.setAttribute('href', '#pwa-' + name); svg.append(use); return svg; };
        const clear = () => { previews.querySelectorAll('video').forEach(video => { video.pause(); video.removeAttribute('src'); video.load(); }); urls.forEach(url => URL.revokeObjectURL(url)); urls = []; previews.replaceChildren(); };
        function render() {
            clear();
            status.textContent = files.length ? '待上传 ' + files.length + ' 个附件' : '';
            for (const [index, file] of files.slice(0, 10).entries()) {
                if (!IMAGE.test(file.name) && !VIDEO.test(file.name)) continue;
                const figure = document.createElement('figure'); figure.className = 'v2-photo-thumb'; figure.title = file.name;
                const media = document.createElement(VIDEO.test(file.name) ? 'video' : 'img');
                media.src = URL.createObjectURL(file); urls.push(media.src);
                if (media.tagName === 'VIDEO') {
                    media.muted = true; media.preload = 'metadata'; media.playsInline = true; media.setAttribute('aria-label', file.name);
                    const badge = document.createElement('span'); badge.className = 'v2-photo-badge'; badge.append(icon('play')); figure.append(badge);
                }
                else media.alt = file.name;
                figure.prepend(media);
                const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'v2-photo-rm'; remove.setAttribute('aria-label', '移除 ' + file.name); remove.append(icon('close'));
                remove.onclick = () => { files.splice(index, 1); render(); onChange(); galleryButton?.focus({preventScroll:true}); };
                figure.append(remove);
                previews.append(figure);
            }
        }
        function changed(event) {
            if (event.target === input || event.target === camera) {
                const added = Array.from(event.target.files || []); event.target.value = '';
                if (!added.length) return;
                const error = validate(files.concat(added), retained());
                if (error) { status.textContent = error; return; }
                files.push(...added); render(); onChange();
            } else if (event.target.name === 'media_remove') {
                const error = validate(files, retained());
                if (error) { event.target.checked = true; status.textContent = error; return; }
                render(); onChange();
            }
        }
        function serialize(event) { event.formData.delete('report_media'); for (const file of files) event.formData.append('report_media', file, file.name); }
        const openGallery = () => input.click(), openCamera = () => camera?.click();
        galleryButton?.addEventListener('click', openGallery); cameraButton?.addEventListener('click', openCamera);
        form.addEventListener('change', changed); form.addEventListener('formdata', serialize); render();
        return {destroy() { clear(); files = []; galleryButton?.removeEventListener('click', openGallery); cameraButton?.removeEventListener('click', openCamera); form.removeEventListener('change', changed); form.removeEventListener('formdata', serialize); }};
    }
    window.FOSWorkorderMedia = {mount, validate};
})();
