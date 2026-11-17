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
        const input = form.querySelector('#pestReportMedia'), previews = form.querySelector('#pestMediaPreviews'), status = form.querySelector('#pestMediaStatus');
        if (!input || !previews || !status) return {destroy() {}};
        let urls = [];
        const clear = () => { previews.querySelectorAll('video').forEach(video => { video.pause(); video.removeAttribute('src'); video.load(); }); urls.forEach(url => URL.revokeObjectURL(url)); urls = []; previews.replaceChildren(); };
        function render() {
            clear();
            const files = Array.from(input.files || []), retained = form.querySelectorAll('[name="media_remove"]:not(:checked)').length;
            const error = validate(files, retained); input.setCustomValidity(error); status.textContent = error || (files.length ? '待上传 ' + files.length + ' 个附件' : '');
            for (const [index, file] of files.slice(0, 10).entries()) {
                if (!IMAGE.test(file.name) && !VIDEO.test(file.name)) continue;
                const figure = document.createElement('figure'), caption = document.createElement('figcaption');
                const media = document.createElement(VIDEO.test(file.name) ? 'video' : 'img');
                media.src = URL.createObjectURL(file); urls.push(media.src);
                if (media.tagName === 'VIDEO') { media.controls = true; media.preload = 'metadata'; media.playsInline = true; }
                else media.alt = '待上传图片 ' + (index + 1);
                caption.textContent = file.name + ' · ' + (file.size / 1024 / 1024).toFixed(1) + ' MB';
                figure.append(media, caption);
                if (typeof DataTransfer !== 'undefined') {
                    const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '移除'; remove.className = 'pest-media-remove'; remove.setAttribute('aria-label', '移除 ' + file.name);
                    remove.onclick = () => { const transfer = new DataTransfer(); files.forEach((item, i) => { if (i !== index) transfer.items.add(item); }); input.files = transfer.files; render(); onChange(); };
                    figure.append(remove);
                }
                previews.append(figure);
            }
        }
        function changed(event) { if (event.target === input || event.target.name === 'media_remove') { render(); onChange(); } }
        form.addEventListener('change', changed); render();
        return {destroy() { clear(); form.removeEventListener('change', changed); }};
    }
    window.FOSWorkorderMedia = {mount, validate};
})();
