/* Native sign-in remains a normal CSRF-protected Django form. */
(() => {
    'use strict';
    const shell = document.querySelector('.auth-shell');
    document.addEventListener('visibilitychange',() => {
        shell.toggleAttribute('data-page-hidden',document.hidden);
    });
    const password = document.getElementById('password');
    const eye = document.getElementById('togglePw');
    eye.addEventListener('click',() => {
        const show = password.type === 'password';
        password.type = show ? 'text' : 'password';
        eye.setAttribute('aria-label',show ? '隐藏密码' : '显示密码');
        eye.setAttribute('aria-pressed',String(show));
        eye.querySelector('use').setAttribute('href',show ? '#pwa-eye-off' : '#pwa-eye');
    });
    const form = document.getElementById('loginForm');
    const submit = document.getElementById('loginBtn');
    const label = document.getElementById('loginLabel');
    const spinner = submit.querySelector('.auth-submit-spinner');
    let submitting = false;
    form.addEventListener('submit',event => {
        if (submitting) { event.preventDefault();return; }
        submitting = true;submit.disabled = true;
        submit.setAttribute('aria-busy','true');label.textContent = '正在登录…';spinner.hidden = false;
    });
    window.addEventListener('pageshow',() => {
        submitting = false;submit.disabled = false;submit.removeAttribute('aria-busy');
        label.textContent = '登录';spinner.hidden = true;
    });
})();
