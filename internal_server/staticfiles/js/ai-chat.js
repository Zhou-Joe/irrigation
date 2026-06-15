/* ai-chat.js — AI data-analyst chat widget for the dashboard.
 * Streams responses from /api/ai/chat (SSE), renders markdown, shows tool progress.
 * Exposes window.AIChat.open() / .toggle() and auto-mounts a launcher button.
 */
(function () {
    'use strict';

    var CSRF = null;
    function getCSRF() {
        if (CSRF) return CSRF;
        var cookie = document.cookie.split('; ').find(function (c) { return c.startsWith('csrftoken='); });
        if (cookie) { CSRF = cookie.split('=')[1]; return CSRF; }
        var el = document.querySelector('[name=csrfmiddlewaretoken]');
        if (el) { CSRF = el.value; return CSRF; }
        return '';
    }

    // Minimal markdown renderer using marked if available; otherwise escapes text.
    function renderMd(text) {
        if (window.marked && typeof window.marked.parse === 'function') {
            try { return window.marked.parse(text); } catch (e) {}
        }
        return '<p>' + String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/\n/g, '<br>') + '</p>';
    }

    var threadId = null;
    var sending = false;

    function el(id) { return document.getElementById(id); }

    function toggle() { var p = el('aiChatPanel'); if (p) { var open = p.style.display === 'none' || !p.style.display; p.style.display = open ? 'flex' : 'none'; if (open) { var i = el('aiChatInput'); if (i) i.focus(); } } }
    function open() { var p = el('aiChatPanel'); if (p) { p.style.display = 'flex'; var i = el('aiChatInput'); if (i) i.focus(); } }

    function addMsg(role, contentHtml) {
        var box = el('aiChatMessages'); if (!box) return null;
        var m = document.createElement('div');
        m.className = 'ai-msg ai-msg-' + role;
        m.innerHTML = contentHtml;
        box.appendChild(m);
        box.scrollTop = box.scrollHeight;
        return m;
    }

    function addUserMsg(text) {
        addMsg('user', '<div class="ai-bubble">' + renderMd(text) + '</div>');
    }

    function startAssistantMsg() {
        var box = el('aiChatMessages'); if (!box) return { el: null, append: function () {} };
        var m = document.createElement('div');
        m.className = 'ai-msg ai-msg-assistant';
        m.innerHTML = '<div class="ai-bubble"></div>';
        var progress = document.createElement('div');
        progress.className = 'ai-tool-progress';
        m.appendChild(progress);
        box.appendChild(m);
        box.scrollTop = box.scrollHeight;
        var bubble = m.querySelector('.ai-bubble');
        return {
            el: m,
            text: '',
            appendToken: function (t) { this.text += t; bubble.innerHTML = renderMd(this.text); box.scrollTop = box.scrollHeight; },
            addTool: function (name, status) {
                var item = document.createElement('div');
                item.className = 'ai-tool-item ai-tool-' + status;
                item.dataset.tool = name;
                item.innerHTML = '<span class="ai-tool-icon">' + (status === 'done' ? '✓' : '⟳') + '</span>' +
                                 '<span class="ai-tool-name">' + name + '</span>';
                progress.appendChild(item);
                progress.style.display = 'flex';
                box.scrollTop = box.scrollHeight;
            },
            markToolDone: function (name) {
                var items = progress.querySelectorAll('.ai-tool-item');
                items.forEach(function (it) {
                    if (it.dataset.tool === name) { it.className = 'ai-tool-item ai-tool-done'; it.querySelector('.ai-tool-icon').textContent = '✓'; }
                });
            },
            addFile: function (name, url, size) {
                var card = document.createElement('a');
                card.className = 'ai-file-card';
                card.href = url;
                card.download = name;
                var ext = name.split('.').pop().toLowerCase();
                var icon = ext === 'xlsx' || ext === 'xls' ? '📊' : (ext === 'csv' ? '📄' : '📎');
                card.innerHTML =
                    '<span class="ai-file-icon">' + icon + '</span>' +
                    '<span class="ai-file-info"><span class="ai-file-name">' + name + '</span>' +
                    '<span class="ai-file-meta">' + _fmtSize(size) + ' · 点击下载</span></span>';
                progress.appendChild(card);
                progress.style.display = 'flex';
                box.scrollTop = box.scrollHeight;
            },
            finalize: function () { progress.style.display = progress.children.length ? 'flex' : 'none'; }
        };
    }

    function _fmtSize(bytes) {
        if (!bytes) return '';
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / 1024 / 1024).toFixed(1) + ' MB';
    }

    function showError(msg) {
        var box = el('aiChatMessages');
        addMsg('assistant', '<div class="ai-bubble ai-error">⚠ ' + msg + '</div>');
    }

    async function send() {
        var input = el('aiChatInput'); if (!input || sending) return;
        var text = input.value.trim(); if (!text) return;
        input.value = '';
        addUserMsg(text);
        var asst = startAssistantMsg();
        sending = true;
        setSending(true);

        try {
            var resp = await fetch('/api/ai/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRF() },
                body: JSON.stringify({ message: text, thread_id: threadId }),
            });

            if (!resp.ok) {
                var errBody = '';
                try { errBody = JSON.parse(await resp.text()); } catch (e) {}
                showError(errBody.error || ('请求失败 (HTTP ' + resp.status + ')'));
                return;
            }

            // Parse SSE stream from the response body.
            var reader = resp.body.getReader();
            var decoder = new TextDecoder('utf-8');
            var buffer = '';
            while (true) {
                var _ref = await reader.read(),
                    done = _ref.done,
                    value = _ref.value;
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                var parts = buffer.split('\n\n');
                buffer = parts.pop();
                for (var i = 0; i < parts.length; i++) {
                    var frame = parts[i];
                    if (frame.indexOf('data:') !== 0) continue;
                    var jsonStr = frame.slice(5).trim();
                    if (!jsonStr) continue;
                    var evt; try { evt = JSON.parse(jsonStr); } catch (e) { continue; }
                    handleEvent(evt, asst);
                }
            }
            asst.finalize();
        } catch (e) {
            showError('网络错误：' + e.message);
        } finally {
            sending = false;
            setSending(false);
        }
    }

    function handleEvent(evt, asst) {
        switch (evt.event) {
            case 'thread': threadId = evt.thread_id; break;
            case 'token': asst.appendToken(evt.text); break;
            case 'tool_start': asst.addTool(evt.name, 'running'); break;
            case 'tool_end': asst.markToolDone(evt.name); break;
            case 'file': asst.addFile(evt.name, evt.url, evt.size); break;
            case 'error': showError(evt.message); break;
            case 'done': break;
        }
    }

    function setSending(v) {
        var btn = el('aiChatSend'); if (!btn) return;
        btn.disabled = v; btn.textContent = v ? '…' : '发送';
    }

    function mount() {
        console.log('[AIChat] mount() start');
        // Launcher button
        var btn = document.createElement('button');
        btn.id = 'aiChatLauncher';
        btn.title = 'AI 数据助手';
        btn.innerHTML = '🤖';
        btn.style.cssText = 'position:fixed;right:24px;bottom:88px;width:52px;height:52px;border-radius:50%;' +
                            'border:3px solid rgba(255,255,255,0.95);background:#2D6A4F;color:#fff;font-size:1.5em;' +
                            'cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,0.25);z-index:99999;display:flex;' +
                            'align-items:center;justify-content:center;transition:transform 0.2s;';
        btn.onclick = toggle;
        btn.onmouseenter = function () { btn.style.transform = 'scale(1.08)'; };
        btn.onmouseleave = function () { btn.style.transform = 'scale(1)'; };
        document.body.appendChild(btn);
        console.log('[AIChat] launcher appended, total body children:', document.body.children.length);

        // Chat panel
        var panel = document.createElement('div');
        panel.id = 'aiChatPanel';
        panel.style.cssText = 'position:fixed;right:24px;bottom:148px;width:min(420px,92vw);height:min(560px,70vh);' +
                              'background:#fff;border-radius:16px;box-shadow:0 8px 32px rgba(0,0,0,0.2);' +
                              'flex-direction:column;overflow:hidden;z-index:2001;display:none;';
        panel.innerHTML =
            '<div style="display:flex;align-items:center;justify-content:space-between;padding:12px 16px;background:#2D6A4F;color:#fff;">' +
              '<div style="font-weight:600;font-size:1em;">🤖 AI 数据助手</div>' +
              '<button id="aiChatClose" style="background:none;border:none;color:#fff;font-size:1.3em;cursor:pointer;line-height:1;">×</button>' +
            '</div>' +
            '<div id="aiChatMessages" style="flex:1;overflow-y:auto;padding:12px;background:#f7f9f8;"></div>' +
            '<div style="display:flex;gap:8px;padding:10px 12px;border-top:1px solid #eee;background:#fff;">' +
              '<textarea id="aiChatInput" placeholder="问：今天有多少工单？最近7天工时趋势？…" rows="1" ' +
                'style="flex:1;border:1px solid #ddd;border-radius:8px;padding:8px 10px;font-size:0.92em;resize:none;max-height:90px;outline:none;font-family:inherit;"></textarea>' +
              '<button id="aiChatSend" style="background:#2D6A4F;color:#fff;border:none;border-radius:8px;padding:0 16px;cursor:pointer;font-weight:600;">发送</button>' +
            '</div>';
        document.body.appendChild(panel);

        el('aiChatClose').onclick = toggle;
        el('aiChatSend').onclick = send;
        var input = el('aiChatInput');
        input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
        });

        // Welcome message
        addMsg('assistant', '<div class="ai-bubble">你好！我是 AI 数据助手，可以帮你查询和分析工单、浇水需求、区域、灌溉数据。试试问我："最近7天有多少工单？"或"按工作类别统计本月工时"</div>');
    }

    // Only mount the launcher if the backend says the AI assistant is available
    // for the current user (feature enabled in admin + manager/super_admin role).
    function mountIfAvailable() {
        fetch('/api/ai/status', { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data && data.available) {
                    mount();
                    console.log('[AIChat] available, launcher mounted');
                } else {
                    console.log('[AIChat] not available for this user/disabled');
                }
            })
            .catch(function () { console.log('[AIChat] status check failed'); });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', mountIfAvailable);
    } else {
        mountIfAvailable();
    }

    window.AIChat = { open: open, toggle: toggle };
})();
