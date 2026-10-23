'use strict';
document.getElementById('pwaRetry').addEventListener('click', function () { window.location.reload(); });
window.addEventListener('online', function () {
    document.getElementById('pwaOfflineStatus').textContent = '网络已恢复，请点击「重新连接」继续。';
});
