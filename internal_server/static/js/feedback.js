(function () {
    'use strict';
    const form = document.querySelector('[data-feedback-form]');
    if (!form) return;
    const text = form.querySelector('textarea'), input = form.querySelector('input[type=file]');
    const count = form.querySelector('[data-feedback-count]'), previews = form.querySelector('[data-feedback-previews]');
    let urls = [];
    function showCount() { count.textContent = text.value.length + ' / 5000'; }
    function clearURLs() { urls.forEach(url => URL.revokeObjectURL(url)); urls = []; }
    function showPhotos() {
        clearURLs(); previews.replaceChildren();
        const files = Array.from(input.files || []);
        input.setCustomValidity(files.length > 5 ? '每条反馈最多上传 5 张照片。' : files.some(file => file.size > 10 * 1024 * 1024) ? '每张照片不能超过 10 MB。' : '');
        for (const [index, file] of files.slice(0, 5).entries()) {
            if (!file.type.startsWith('image/')) continue;
            const figure = document.createElement('figure'), image = document.createElement('img'), caption = document.createElement('figcaption');
            image.src = URL.createObjectURL(file); urls.push(image.src); image.alt = '待上传照片 ' + (index + 1);
            caption.textContent = file.name; figure.append(image, caption);
            if (typeof DataTransfer !== 'undefined') {
                const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '×'; remove.setAttribute('aria-label', '移除照片 ' + file.name);
                remove.onclick = () => { const transfer = new DataTransfer(); files.forEach((item, i) => { if (i !== index) transfer.items.add(item); }); input.files = transfer.files; showPhotos(); };
                figure.append(remove);
            }
            previews.append(figure);
        }
    }
    text.addEventListener('input', showCount); input.addEventListener('change', showPhotos);
    form.addEventListener('submit', () => { if (form.checkValidity()) { const button = form.querySelector('button[type=submit]'); button.disabled = true; button.textContent = '正在提交…'; } });
    window.addEventListener('pagehide', clearURLs);
    window.addEventListener('pageshow', () => { const button = form.querySelector('button[type=submit]'); button.disabled = false; button.textContent = '提交反馈 ↗'; showPhotos(); });
    showCount();
})();
