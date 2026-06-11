# Zone Remarks (备注/备注确认) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add remark (备注) and confirmed-remark (备注确认) fields to Zone, with AJAX-powered add/confirm/triage UI on the zone detail page.

**Architecture:** Two new TextField fields on Zone storing JSON arrays. Three AJAX endpoints for add/confirm/move operations. Zone detail page gains interactive remark sections with inline forms.

**Tech Stack:** Django 4.2, plain JS fetch(), existing template patterns

---

### Task 1: Add model fields + migration

**Files:**
- Modify: `core/models.py:147-148` (after existing notes fields)
- Create: `core/migrations/0042_zone_remarks.py`

- [ ] **Step 1: Add fields to Zone model**

In `core/models.py`, after line 148 (`irrigation_management_notes`), add:

```python
    remarks = models.TextField(blank=True, default='', verbose_name='备注')
    confirmed_remarks = models.TextField(blank=True, default='', verbose_name='备注确认')
```

- [ ] **Step 2: Generate and apply migration**

Run:
```bash
cd /Users/chen/development/maxicom/internal_server && source /Users/chen/development/maxicom/.venv/bin/activate && DJANGO_SETTINGS_MODULE=config.settings python manage.py makemigrations core --name zone_remarks
```

Then:
```bash
DJANGO_SETTINGS_MODULE=config.settings python manage.py migrate
```

- [ ] **Step 3: Commit**

```bash
git add core/models.py core/migrations/0042_zone_remarks.py
git commit -m "feat: add remarks and confirmed_remarks fields to Zone model"
```

---

### Task 2: Add URL routes and view functions

**Files:**
- Modify: `core/urls.py:60` (near zone detail route)
- Modify: `core/views.py` (after `zone_detail_page` function)

- [ ] **Step 1: Add 3 URL routes in `core/urls.py`**

After the `zone_detail` route (line 60), add:

```python
    path('zone/<int:zone_id>/remark/add/', views.zone_remark_add, name='zone_remark_add'),
    path('zone/<int:zone_id>/remark/<int:index>/confirm/', views.zone_remark_confirm, name='zone_remark_confirm'),
    path('zone/<int:zone_id>/remark/<int:index>/move/', views.zone_remark_move, name='zone_remark_move'),
```

- [ ] **Step 2: Add helper to get user's display name**

In `core/views.py`, add a helper function near the existing `_check_zone_admin`:

```python
def _get_user_display_name(request):
    """Get the current user's display name from their profile."""
    from .models import ManagerProfile, Worker
    for Model in (ManagerProfile, Worker):
        try:
            profile = Model.objects.get(user=request.user, active=True)
            return profile.full_name or request.user.username
        except Model.DoesNotExist:
            continue
    return request.user.username
```

- [ ] **Step 3: Add `zone_remark_add` view**

```python
@login_required(login_url='core:login')
def zone_remark_add(request, zone_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    zone = get_object_or_404(Zone, pk=zone_id)
    date = request.POST.get('date', '').strip()
    content = request.POST.get('content', '').strip()
    if not content:
        return JsonResponse({'error': '内容不能为空'}, status=400)
    if not date:
        from datetime import date as date_cls
        date = date_cls.today().isoformat()
    author = _get_user_display_name(request)
    remarks = json.loads(zone.remarks) if zone.remarks else []
    remarks.insert(0, {'date': date, 'content': content, 'author': author})
    zone.remarks = json.dumps(remarks, ensure_ascii=False)
    zone.save(update_fields=['remarks'])
    return JsonResponse({'success': True, 'remark': {'date': date, 'content': content, 'author': author}})
```

- [ ] **Step 4: Add `zone_remark_confirm` view**

```python
@login_required(login_url='core:login')
def zone_remark_confirm(request, zone_id, index):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    if not _check_zone_admin(request):
        return JsonResponse({'error': '无权限'}, status=403)
    zone = get_object_or_404(Zone, pk=zone_id)
    remarks = json.loads(zone.remarks) if zone.remarks else []
    if index < 0 or index >= len(remarks):
        return JsonResponse({'error': '索引无效'}, status=400)
    remark = remarks.pop(index)
    confirm_reply = request.POST.get('confirm_reply', '').strip()
    confirm_author = _get_user_display_name(request)
    from datetime import date as date_cls
    confirmed = {
        **remark,
        'confirm_date': date_cls.today().isoformat(),
        'confirm_reply': confirm_reply,
        'confirm_author': confirm_author,
    }
    confirmed_list = json.loads(zone.confirmed_remarks) if zone.confirmed_remarks else []
    confirmed_list.insert(0, confirmed)
    zone.remarks = json.dumps(remarks, ensure_ascii=False)
    zone.confirmed_remarks = json.dumps(confirmed_list, ensure_ascii=False)
    zone.save(update_fields=['remarks', 'confirmed_remarks'])
    return JsonResponse({'success': True, 'confirmed': confirmed})
```

- [ ] **Step 5: Add `zone_remark_move` view**

```python
@login_required(login_url='core:login')
def zone_remark_move(request, zone_id, index):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    if not _check_zone_admin(request):
        return JsonResponse({'error': '无权限'}, status=403)
    zone = get_object_or_404(Zone, pk=zone_id)
    target = request.POST.get('target', '').strip()
    if target not in ('irrigation', 'equipment'):
        return JsonResponse({'error': '目标无效'}, status=400)
    confirmed_list = json.loads(zone.confirmed_remarks) if zone.confirmed_remarks else []
    if index < 0 or index >= len(confirmed_list):
        return JsonResponse({'error': '索引无效'}, status=400)
    entry = confirmed_list.pop(index)
    note = {'date': entry.get('date', ''), 'content': entry.get('content', '')}
    if target == 'irrigation':
        notes = json.loads(zone.irrigation_management_notes) if zone.irrigation_management_notes else []
        notes.insert(0, note)
        zone.irrigation_management_notes = json.dumps(notes, ensure_ascii=False)
        zone.save(update_fields=['confirmed_remarks', 'irrigation_management_notes'])
    else:
        notes = json.loads(zone.equipment_maintenance_notes) if zone.equipment_maintenance_notes else []
        notes.insert(0, note)
        zone.equipment_maintenance_notes = json.dumps(notes, ensure_ascii=False)
        zone.save(update_fields=['confirmed_remarks', 'equipment_maintenance_notes'])
    zone.confirmed_remarks = json.dumps(confirmed_list, ensure_ascii=False)
    zone.save(update_fields=['confirmed_remarks'])
    return JsonResponse({'success': True, 'target': target, 'note': note})
```

- [ ] **Step 6: Update `zone_detail_page` context**

In the `zone_detail_page` view, after the existing `_sort_notes` calls for `equip_notes` and `irrig_notes` (around line 1823), add:

```python
    remarks = _sort_notes(json.loads(zone.remarks)) if zone.remarks else []
    confirmed_remarks = _sort_notes(json.loads(zone.confirmed_remarks)) if zone.confirmed_remarks else []
    is_manager = _check_zone_admin(request)
```

Add to the context dict:
```python
    'remarks': remarks,
    'confirmed_remarks': confirmed_remarks,
    'is_manager': is_manager,
```

Also add `@ensure_csrf_cookie` decorator to `zone_detail_page` so AJAX calls can read the CSRF cookie:

```python
from django.views.decorators.csrf import ensure_csrf_cookie

@ensure_csrf_cookie
@login_required(login_url='core:login')
def zone_detail_page(request, zone_id):
```

- [ ] **Step 7: Commit**

```bash
git add core/urls.py core/views.py
git commit -m "feat: add remark add/confirm/move endpoints and update zone detail context"
```

---

### Task 3: Add remark UI to zone detail template

**Files:**
- Modify: `core/templates/core/zone_detail_page.html`

This is the largest task. Add two new sections between the existing notes sections and the work reports section, plus JavaScript for AJAX interactions.

- [ ] **Step 1: Add remark sections in HTML**

After the existing 灌溉管理记录 section (after line ~508), add:

```html
<!-- 备注 Section -->
<div class="detail-section">
    <h2 class="section-title">备注</h2>
    <div id="remark-form" style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;">
        <input type="date" id="remark-date" value="{{ today }}" style="padding:4px 8px;border:1px solid #ddd;border-radius:4px;">
        <input type="text" id="remark-content" placeholder="备注内容..." style="flex:1;min-width:200px;padding:4px 8px;border:1px solid #ddd;border-radius:4px;">
        <button type="button" id="remark-add-btn" onclick="addRemark()" style="padding:4px 12px;background:#28a745;color:white;border:none;border-radius:4px;cursor:pointer;">添加</button>
    </div>
    <div id="remarks-list">
    {% for remark in remarks %}
        <div class="note-entry" data-index="{{ forloop.counter0 }}">
            <span class="note-date">{{ remark.date }}</span>
            <span class="note-content">{{ remark.content }}</span>
            <span style="color:#888;font-size:0.85em;">({{ remark.author }})</span>
            {% if is_manager %}
            <button type="button" class="remark-confirm-btn" onclick="showConfirmForm(this, {{ forloop.counter0 }})" style="margin-left:8px;padding:2px 8px;background:#007bff;color:white;border:none;border-radius:3px;cursor:pointer;font-size:0.8em;">确认</button>
            <div class="confirm-form" style="display:none;margin-top:6px;">
                <input type="text" class="confirm-reply" placeholder="确认回复..." style="padding:2px 6px;border:1px solid #ddd;border-radius:3px;width:70%;">
                <button type="button" onclick="confirmRemark({{ forloop.counter0 }}, this)" style="padding:2px 8px;background:#17a2b8;color:white;border:none;border-radius:3px;cursor:pointer;font-size:0.8em;">提交</button>
                <button type="button" onclick="this.parentElement.style.display='none'" style="padding:2px 8px;border:1px solid #ccc;border-radius:3px;cursor:pointer;font-size:0.8em;">取消</button>
            </div>
            {% endif %}
        </div>
    {% empty %}
        <div class="empty-state">暂无备注</div>
    {% endfor %}
    </div>
</div>

<!-- 备注确认 Section -->
<div class="detail-section">
    <h2 class="section-title">备注确认</h2>
    <div id="confirmed-list">
    {% for item in confirmed_remarks %}
        <div class="note-entry confirmed-entry" data-index="{{ forloop.counter0 }}">
            <div>
                <span class="note-date">{{ item.date }}</span>
                <span class="note-content">{{ item.content }}</span>
                <span style="color:#888;font-size:0.85em;">({{ item.author }})</span>
            </div>
            <div style="margin-top:4px;padding-left:16px;border-left:3px solid #28a745;font-size:0.9em;">
                <span style="color:#888;">{{ item.confirm_date }}</span>
                <span style="color:#28a745;">{{ item.confirm_reply }}</span>
                <span style="color:#888;font-size:0.85em;">({{ item.confirm_author }})</span>
            </div>
            {% if is_manager %}
            <div style="margin-top:6px;">
                <button type="button" onclick="moveRemark({{ forloop.counter0 }}, 'irrigation')" style="padding:2px 8px;background:#6f42c1;color:white;border:none;border-radius:3px;cursor:pointer;font-size:0.8em;">转至灌溉管理记录</button>
                <button type="button" onclick="moveRemark({{ forloop.counter0 }}, 'equipment')" style="padding:2px 8px;background:#fd7e14;color:white;border:none;border-radius:3px;cursor:pointer;font-size:0.8em;">转至设备维护记录</button>
            </div>
            {% endif %}
        </div>
    {% empty %}
        <div class="empty-state">暂无确认备注</div>
    {% endfor %}
    </div>
</div>
```

Also add `today` to the view context (in `zone_detail_page`):
```python
    'today': date.today().isoformat(),
```

- [ ] **Step 2: Add JavaScript before `{% endblock %}`**

```html
<script>
(function() {
    const zoneId = {{ zone.id }};
    const csrfToken = '{{ csrf_token }}';

    function getCSRF() {
        const cookie = document.cookie.split('; ').find(c => c.startsWith('csrftoken='));
        return cookie ? cookie.split('=')[1] : csrfToken;
    }

    function postAction(url, data) {
        const fd = new FormData();
        for (const [k, v] of Object.entries(data)) fd.append(k, v);
        return fetch(url, {
            method: 'POST',
            body: fd,
            headers: {'X-CSRFToken': getCSRF(), 'X-Requested-With': 'XMLHttpRequest'}
        }).then(r => r.json());
    }

    window.addRemark = function() {
        const date = document.getElementById('remark-date').value;
        const content = document.getElementById('remark-content').value.trim();
        if (!content) { alert('请输入备注内容'); return; }
        postAction(`/zone/${zoneId}/remark/add/`, {date, content}).then(data => {
            if (data.success) {
                location.reload();
            } else {
                alert(data.error || '添加失败');
            }
        });
    };

    // Enter key to submit
    document.getElementById('remark-content').addEventListener('keydown', function(e) {
        if (e.key === 'Enter') window.addRemark();
    });

    window.showConfirmForm = function(btn, index) {
        const form = btn.nextElementSibling;
        form.style.display = form.style.display === 'none' ? 'block' : 'none';
    };

    window.confirmRemark = function(index, btn) {
        const form = btn.parentElement;
        const reply = form.querySelector('.confirm-reply').value.trim();
        postAction(`/zone/${zoneId}/remark/${index}/confirm/`, {confirm_reply: reply}).then(data => {
            if (data.success) {
                location.reload();
            } else {
                alert(data.error || '确认失败');
            }
        });
    };

    window.moveRemark = function(index, target) {
        const label = target === 'irrigation' ? '灌溉管理记录' : '设备维护记录';
        if (!confirm(`确认转至${label}？`)) return;
        postAction(`/zone/${zoneId}/remark/${index}/move/`, {target}).then(data => {
            if (data.success) {
                location.reload();
            } else {
                alert(data.error || '转移失败');
            }
        });
    };
})();
</script>
```

- [ ] **Step 3: Commit**

```bash
git add core/templates/core/zone_detail_page.html
git commit -m "feat: add remark sections with AJAX add/confirm/move UI to zone detail page"
```

---

### Task 4: Manual verification

- [ ] **Step 1: Start dev server and test**

```bash
cd /Users/chen/development/maxicom/internal_server && source /Users/chen/development/maxicom/.venv/bin/activate && DJANGO_SETTINGS_MODULE=config.settings python manage.py runserver
```

Test in browser:
1. Navigate to a zone detail page
2. See 备注 section with add form, 备注确认 section below
3. Add a remark → page reloads, remark appears in list
4. As manager, click 确认 → enter reply → submit → page reloads, remark moves to 备注确认
5. Click "转至灌溉管理记录" → confirm → page reloads, entry appears in 灌溉管理记录, removed from 备注确认
6. Verify non-manager users cannot see confirm/move buttons
