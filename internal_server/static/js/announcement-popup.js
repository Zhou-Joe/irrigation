(function () {
    var mounted=document.getElementById('dashboardWorkspace');
    var queue = [];
    window.__annQueue = queue;
    function load() {
        var el = document.getElementById('announcements-data');
        if (!el) return;
        try { queue = window.__annQueue = JSON.parse(el.textContent || '[]'); } catch (e) { queue = []; }
        showCurrent();
    }
    function showCurrent() {
        if(!mounted?.isConnected)return;
        if (!queue.length) { document.getElementById('annPopup').style.display = 'none'; return; }
        var a = queue[0];
        document.getElementById('annTitle').textContent = a.title;
        document.getElementById('annTime').textContent = a.time || '';
        document.getElementById('annBody').textContent = a.body;
        document.getElementById('annCounter').textContent = queue.length > 1 ? (queue.length + ' 条待确认') : '';
        document.getElementById('annAckBtn').disabled = false;
        document.getElementById('annPopup').style.display = 'flex';
    }
    window.ackAnnouncement = function () {
        if (!queue.length) return;
        var a = queue[0];
        var btn = document.getElementById('annAckBtn');
        btn.disabled = true;
        var csrf = (document.cookie.split('; ').find(function (c) { return c.indexOf('csrftoken=') === 0; }) || '').split('=')[1] || '';
        fetch('/api/announcements/' + a.id + '/acknowledge/', {
            method: 'POST',
            headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': csrf },
        }).then(function (r) { if(!r.ok)throw Error('确认失败');return r.json(); }).then(function (d) {
            if(!d.success)throw Error('确认失败');
            queue.shift();            // remove the acknowledged one locally
            window.__annQueue = queue;
            showCurrent();           // show next or hide
        }).catch(function () {
            btn.disabled = false;
            alert('网络错误，请重试');
        });
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', load); else load();
})();
