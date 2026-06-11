# Landmarks (地标) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Landmark entity with drawn boundaries, automatic zone assignment via polygon overlap, dashboard sidebar filter, and optional map overlay.

**Architecture:** New `Landmark` model + M2M `ZoneLandmarkAssignment` through table. Shapely-based overlap calculation triggered manually from settings page. Landmark data serialized to dashboard like zones/pipelines.

**Tech Stack:** Django, Leaflet.js, Shapely, existing zone_batch_draw pattern

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `core/models.py` | Modify (after line 234) | Add `Landmark` and `ZoneLandmarkAssignment` models |
| `core/migrations/0043_landmark.py` | Create | Migration for new models |
| `core/urls.py` | Modify | Add landmark CRUD + recalculate URLs |
| `core/views.py` | Modify | Add landmark views + recalculate endpoint |
| `core/templates/core/settings.html` | Modify (after line 301) | Add landmark management card |
| `core/templates/core/landmark_draw.html` | Create | Boundary drawing page for a single landmark |
| `core/templates/core/dashboard.html` | Modify | Add landmark filter in sidebar, layer toggle, data script tag |
| `static/js/map.js` | Modify | Add landmark layer rendering + filter logic |
| `staticfiles/js/map.js` | Sync | Copy of static/js/map.js |

---

### Task 1: Add Landmark and ZoneLandmarkAssignment models

**Files:**
- Modify: `internal_server/core/models.py` (insert after line 234, before Pipeline class)

- [ ] **Step 1: Add models**

Insert after line 234 in `core/models.py` (before the `Pipeline` class):

```python
class Landmark(models.Model):
    """地标 — general place name with drawn boundary for zone grouping."""

    name = models.CharField('名称', max_length=255, unique=True)
    boundary_points = models.JSONField('边界坐标', default=list)
    boundary_color = models.CharField('边界颜色', max_length=7, default='#E8590C')
    center = models.JSONField('中心点', null=True, blank=True)
    area_sqm = models.FloatField('面积(m²)', null=True, blank=True)
    order = models.PositiveIntegerField('排序', default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'name']
        verbose_name = '地标'
        verbose_name_plural = '地标'

    def __str__(self):
        return self.name


class ZoneLandmarkAssignment(models.Model):
    """Persisted zone↔landmark relationship (calculated on demand)."""

    zone = models.ForeignKey(Zone, on_delete=models.CASCADE, related_name='landmark_assignments')
    landmark = models.ForeignKey(Landmark, on_delete=models.CASCADE, related_name='zone_assignments')
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('zone', 'landmark')

    def __str__(self):
        return f'{self.zone.code} → {self.landmark.name}'
```

- [ ] **Step 2: Make migration**

Run: `cd /Users/chen/development/maxicom/internal_server && python manage.py makemigrations core --name landmark`

- [ ] **Step 3: Apply migration**

Run: `cd /Users/chen/development/maxicom/internal_server && python manage.py migrate`

- [ ] **Step 4: Commit**

```bash
git add internal_server/core/models.py internal_server/core/migrations/
git commit -m "feat: add Landmark and ZoneLandmarkAssignment models"
```

---

### Task 2: Add landmark URLs

**Files:**
- Modify: `internal_server/core/urls.py` (add after existing landmark-related lines, near the region CRUD block)

- [ ] **Step 1: Add URL patterns**

In `core/urls.py`, after the region CRUD block (around line 79), add:

```python
    # Landmark CRUD
    path('settings/landmark/new/', views.landmark_new, name='landmark_new'),
    path('settings/landmark/<int:landmark_id>/', views.landmark_edit, name='landmark_edit'),
    path('settings/landmark/<int:landmark_id>/delete/', views.landmark_delete, name='landmark_delete'),
    path('api/landmarks/', views.landmarks_api, name='landmarks_api'),
    path('api/landmarks/recalculate/', views.landmarks_recalculate, name='landmarks_recalculate'),
```

- [ ] **Step 2: Commit**

```bash
git add internal_server/core/urls.py
git commit -m "feat: add landmark URL patterns"
```

---

### Task 3: Add landmark views (CRUD + recalculate)

**Files:**
- Modify: `internal_server/core/views.py`

- [ ] **Step 1: Add views**

Add the following views to `core/views.py` (before or after the existing region/patch CRUD views). Also add the helper function for overlap calculation.

At the top of the file, ensure these imports exist (add any that are missing):

```python
import json
from django.views.decorators.http import require_POST
```

Add the recalculate helper function (place it near other helper functions):

```python
def _recalculate_landmark_assignments():
    """Recalculate all zone↔landmark assignments based on boundary overlap."""
    try:
        from shapely.geometry import shape, MultiPolygon
    except ImportError:
        return -1

    from .models import Landmark, ZoneLandmarkAssignment, Zone

    ZoneLandmarkAssignment.objects.all().delete()

    landmarks = Landmark.objects.exclude(boundary_points=[])
    zones = Zone.objects.exclude(boundary_points=[])
    count = 0

    for landmark in landmarks:
        landmark_geom = _boundary_points_to_shapely(landmark.boundary_points)
        if landmark_geom is None:
            continue
        for zone in zones:
            zone_geom = _boundary_points_to_shapely(zone.boundary_points)
            if zone_geom is None:
                continue
            if landmark_geom.intersects(zone_geom):
                ZoneLandmarkAssignment.objects.create(zone=zone, landmark=landmark)
                count += 1

    return count


def _boundary_points_to_shapely(boundary_points):
    """Convert JSON boundary_points to a Shapely geometry."""
    from shapely.geometry import Polygon, MultiPolygon

    if not boundary_points or len(boundary_points) == 0:
        return None

    def to_coord(p):
        if isinstance(p, dict):
            return (p.get('lng', p.get('longitude', 0)), p.get('lat', p.get('latitude', 0)))
        if isinstance(p, (list, tuple)) and len(p) >= 2:
            return (p[1], p[0])  # [lat, lng] → (lng, lat) for Shapely
        return None

    first = boundary_points[0]
    if isinstance(first, list) and len(first) > 0 and (isinstance(first[0], (list, dict))):
        rings = boundary_points
    elif isinstance(first, (dict, list)):
        rings = [boundary_points]
    else:
        return None

    polygons = []
    for ring in rings:
        coords = [to_coord(p) for p in ring]
        coords = [c for c in coords if c is not None]
        if len(coords) >= 3:
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            polygons.append(Polygon(coords))

    if len(polygons) == 0:
        return None
    if len(polygons) == 1:
        return polygons[0]
    return MultiPolygon(polygons)
```

Add the CRUD views:

```python
def landmark_new(request):
    from .models import Landmark
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            return JsonResponse({'error': '名称不能为空'}, status=400)
        boundary_raw = request.POST.get('boundary_points', '[]')
        boundary_color = request.POST.get('boundary_color', '#E8590C')
        try:
            boundary_data = json.loads(boundary_raw)
        except json.JSONDecodeError:
            return JsonResponse({'error': '边界数据格式错误'}, status=400)
        landmark = Landmark(name=name, boundary_points=boundary_data, boundary_color=boundary_color)
        landmark.center = get_zone_center(boundary_data)
        landmark.save()
        return JsonResponse({'success': True, 'id': landmark.id, 'name': landmark.name})
    return render(request, 'core/landmark_draw.html', {'landmark': None})


def landmark_edit(request, landmark_id):
    from .models import Landmark
    landmark = get_object_or_404(Landmark, pk=landmark_id)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if name:
            landmark.name = name
        boundary_raw = request.POST.get('boundary_points', '')
        if boundary_raw:
            try:
                boundary_data = json.loads(boundary_raw)
                landmark.boundary_points = boundary_data
                landmark.center = get_zone_center(boundary_data)
            except json.JSONDecodeError:
                return JsonResponse({'error': '边界数据格式错误'}, status=400)
        boundary_color = request.POST.get('boundary_color')
        if boundary_color:
            landmark.boundary_color = boundary_color
        landmark.save()
        return JsonResponse({'success': True, 'id': landmark.id, 'name': landmark.name})
    return render(request, 'core/landmark_draw.html', {'landmark': landmark})


def landmark_delete(request, landmark_id):
    from .models import Landmark
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    landmark = get_object_or_404(Landmark, pk=landmark_id)
    landmark.delete()
    return JsonResponse({'success': True})


def landmarks_api(request):
    from .models import Landmark, ZoneLandmarkAssignment
    landmarks = Landmark.objects.order_by('order', 'name')
    data = []
    for lm in landmarks:
        zone_count = ZoneLandmarkAssignment.objects.filter(landmark=lm).count()
        data.append({
            'id': lm.id,
            'name': lm.name,
            'boundary_points': lm.boundary_points,
            'boundary_color': lm.boundary_color,
            'center': lm.center,
            'area_sqm': lm.area_sqm,
            'zone_count': zone_count,
        })
    return JsonResponse(data, safe=False)


def landmarks_recalculate(request):
    from .models import Landmark
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    count = _recalculate_landmark_assignments()
    if count < 0:
        return JsonResponse({'error': 'Shapely library not installed. Run: pip install shapely'}, status=500)
    total_zones = Landmark.objects.count()
    return JsonResponse({'success': True, 'assignments': count, 'landmarks': total_zones})
```

Also add landmarks data to the `settings_page` view context. Find the context dict (around line 1248) and add:

```python
            'landmarks': Landmark.objects.order_by('order', 'name'),
            'landmark_zone_counts': {
                lm.id: ZoneLandmarkAssignment.objects.filter(landmark=lm).count()
                for lm in Landmark.objects.all()
            },
```

And add imports at the top of `settings_page` if not already there:

```python
from .models import Landmark, ZoneLandmarkAssignment
```

- [ ] **Step 2: Commit**

```bash
git add internal_server/core/views.py
git commit -m "feat: add landmark CRUD views and recalculate endpoint"
```

---

### Task 4: Create landmark boundary drawing page

**Files:**
- Create: `internal_server/core/templates/core/landmark_draw.html`

This reuses the same Leaflet drawing pattern as `zone_batch_draw.html` but simplified for a single landmark.

- [ ] **Step 1: Create the template**

Create `internal_server/core/templates/core/landmark_draw.html`:

```html
{% extends "base.html" %}
{% load static %}

{% block title %}{% if landmark %}编辑地标{% else %}新建地标{% endif %}{% endblock %}

{% block extra_css %}
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<link rel="stylesheet" href="{% static 'css/settings.css' %}" />
<style>
    body { margin: 0; }
    .ld-container { display: flex; flex-direction: column; height: 100vh; }
    .ld-header { padding: 12px 16px; display: flex; align-items: center; gap: 12px; background: #fff; border-bottom: 1px solid #e0e0e0; flex-shrink: 0; }
    .ld-header input[type="text"] { flex: 1; padding: 6px 10px; border: 1px solid #ccc; border-radius: 6px; font-size: 14px; }
    .ld-header input[type="color"] { width: 40px; height: 32px; border: 1px solid #ccc; border-radius: 4px; cursor: pointer; padding: 2px; }
    .ld-map-wrap { flex: 1; position: relative; }
    #ldMap { width: 100%; height: 100%; }
    .ld-toolbar { position: absolute; top: 10px; left: 10px; z-index: 1000; display: flex; gap: 6px; }
    .ld-toolbar button { padding: 6px 12px; background: #fff; border: 1px solid #ccc; border-radius: 6px; cursor: pointer; font-size: 13px; box-shadow: 0 1px 4px rgba(0,0,0,0.15); }
    .ld-toolbar button.active { background: #52B788; color: #fff; border-color: #52B788; }
    .ld-toolbar button:hover { background: #f0f0f0; }
    .ld-toolbar button.active:hover { background: #40916C; }
    .btn-save { background: #2D6A4F !important; color: #fff !important; border-color: #2D6A4F !important; }
    .btn-save:hover { background: #1B4332 !important; }
    .btn-close { background: #888 !important; color: #fff !important; border-color: #888 !important; }
</style>
{% endblock %}

{% block content %}
<div class="ld-container">
    <div class="ld-header">
        <input type="text" id="landmarkName" placeholder="地标名称" value="{{ landmark.name|default:'' }}">
        <input type="color" id="landmarkColor" value="{{ landmark.boundary_color|default:'#E8590C' }}">
        <button class="btn-save" onclick="saveLandmark()">保存</button>
        <button class="btn-close" onclick="window.close()">关闭</button>
    </div>
    <div class="ld-map-wrap">
        <div class="ld-toolbar">
            <button id="btnDraw" onclick="startDraw()">绘制边界</button>
            <button id="btnUndo" onclick="undoPoint()">撤销</button>
            <button onclick="clearBoundary()">清除</button>
        </div>
        <div id="ldMap"></div>
    </div>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
(function() {
    const editMode = {{ landmark.id|default:'null' }};
    const existingBoundary = {{ landmark.boundary_points|safe|default:'[]' }};
    const existingCenter = {{ landmark.center|safe|default:'null' }};

    const map = L.map('ldMap', { center: [31.1558, 121.6688], zoom: 16, maxZoom: 22 });
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        attribution: 'Esri', maxNativeZoom: 19, maxZoom: 22
    }).addTo(map);

    let drawnPoints = [];
    let drawnMarkers = [];
    let drawnPolyline = null;
    let finalPolygon = null;
    let isDrawing = false;

    function loadExisting() {
        if (!existingBoundary || existingBoundary.length === 0) return;
        let rings;
        const first = existingBoundary[0];
        if (Array.isArray(first) && first.length > 0 && (Array.isArray(first[0]) || first[0]?.lat !== undefined)) {
            rings = existingBoundary;
        } else {
            rings = [existingBoundary];
        }
        rings.forEach(ring => {
            const latLngs = ring.map(p => {
                if (Array.isArray(p)) return [p[0], p[1]];
                if (p.lat !== undefined) return [p.lat, p.lng];
                return null;
            }).filter(Boolean);
            if (latLngs.length >= 3) {
                L.polygon(latLngs, { color: document.getElementById('landmarkColor').value, weight: 2, fillOpacity: 0.15 }).addTo(map);
                map.fitBounds(L.latLngBounds(latLngs), { padding: [30, 30] });
            }
        });
        // Store for save
        drawnPoints = rings;
    }
    loadExisting();

    // Load existing zones as reference
    fetch('/api/zones-by-patch/').then(r => r.json()).then(data => {
        // Silently ignore if endpoint requires patch_id
    }).catch(() => {});

    window.startDraw = function() {
        isDrawing = !isDrawing;
        document.getElementById('btnDraw').classList.toggle('active', isDrawing);
        document.getElementById('ldMap').style.cursor = isDrawing ? 'crosshair' : '';
        if (!isDrawing && drawnPoints.length > 0) {
            finishRing();
        }
    };

    map.on('click', function(e) {
        if (!isDrawing) return;
        drawnPoints.push([e.latlng.lat, e.latlng.lng]);
        const marker = L.circleMarker(e.latlng, { radius: 4, color: '#E8590C', fillColor: '#E8590C', fillOpacity: 1 }).addTo(map);
        drawnMarkers.push(marker);
        updateDrawingLine();
    });

    function updateDrawingLine() {
        if (drawnPolyline) map.removeLayer(drawnPolyline);
        if (drawnPoints.length < 2) return;
        drawnPolyline = L.polyline(drawnPoints.map(p => Array.isArray(p) ? p : [p[0], p[1]]), { color: '#E8590C', weight: 2, dashArray: '6 4' }).addTo(map);
    }

    function finishRing() {
        if (drawnMarkers.length > 0) {
            drawnMarkers.forEach(m => map.removeLayer(m));
            drawnMarkers = [];
        }
        if (drawnPolyline) { map.removeLayer(drawnPolyline); drawnPolyline = null; }
    }

    window.undoPoint = function() {
        if (drawnMarkers.length > 0) {
            const m = drawnMarkers.pop();
            map.removeLayer(m);
            drawnPoints.pop();
            updateDrawingLine();
        }
    };

    window.clearBoundary = function() {
        drawnMarkers.forEach(m => map.removeLayer(m));
        drawnMarkers = [];
        if (drawnPolyline) { map.removeLayer(drawnPolyline); drawnPolyline = null; }
        if (finalPolygon) { map.removeLayer(finalPolygon); finalPolygon = null; }
        drawnPoints = [];
        isDrawing = false;
        document.getElementById('btnDraw').classList.remove('active');
        document.getElementById('ldMap').style.cursor = '';
    };

    window.saveLandmark = function() {
        const name = document.getElementById('landmarkName').value.trim();
        if (!name) { alert('请输入地标名称'); return; }
        const color = document.getElementById('landmarkColor').value;
        let boundary;
        if (Array.isArray(drawnPoints) && drawnPoints.length > 0 && Array.isArray(drawnPoints[0]) && drawnPoints.length >= 3) {
            // New drawing: wrap in array for multi-polygon format
            boundary = [drawnPoints];
        } else if (existingBoundary && existingBoundary.length > 0) {
            boundary = existingBoundary;
        } else {
            alert('请先绘制边界');
            return;
        }
        const body = new FormData();
        body.append('name', name);
        body.append('boundary_points', JSON.stringify(boundary));
        body.append('boundary_color', color);
        const url = editMode ? '/settings/landmark/' + editMode + '/' : '/settings/landmark/new/';
        fetch(url, { method: 'POST', body: body }).then(r => r.json()).then(data => {
            if (data.error) { alert(data.error); return; }
            alert('保存成功');
            if (window.opener) window.opener.location.reload();
        }).catch(err => alert('保存失败: ' + err));
    };
})();
</script>
{% endblock %}
```

- [ ] **Step 2: Commit**

```bash
git add internal_server/core/templates/core/landmark_draw.html
git commit -m "feat: add landmark boundary drawing page"
```

---

### Task 5: Add landmark management section to settings page

**Files:**
- Modify: `internal_server/core/templates/core/settings.html` (insert after line 301, before line 304)

- [ ] **Step 1: Add landmark management card**

In `settings.html`, after the Pipeline Management card (after line 301) and before the back link container (line 304), insert:

```html
        <!-- Landmark Management -->
        <div class="settings-card">
            <div class="settings-card-header" onclick="toggleCardBody(this, 'landmarkBody', 'landmarkIndicator')">
                <h2><span class="collapse-indicator" id="landmarkIndicator">▼</span> 地标管理</h2>
                <div class="header-actions" onclick="event.stopPropagation()">
                    <a href="{% url 'core:landmark_new' %}" class="btn btn-sm btn-primary" target="_blank">+ 新建</a>
                    <button class="btn btn-sm btn-secondary" onclick="recalcLandmarks()" title="重新计算区域归属">重新分配</button>
                </div>
            </div>
            <div class="settings-card-body" id="landmarkBody">
                <table class="settings-table">
                    <thead>
                        <tr>
                            <th><input type="checkbox" onchange="toggleAllLandmarks(this.checked)"></th>
                            <th>名称</th>
                            <th>关联区域数</th>
                            <th>操作</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for landmark in landmarks %}
                        <tr>
                            <td><input type="checkbox" class="landmark-check" data-id="{{ landmark.id }}"></td>
                            <td><span style="display:inline-block;width:12px;height:12px;border-radius:2px;background:{{ landmark.boundary_color }};vertical-align:middle;margin-right:6px;"></span>{{ landmark.name }}</td>
                            <td>{{ landmark_zone_counts|default_if_none:0 }}</td>
                            <td>
                                <a href="{% url 'core:landmark_edit' landmark.id %}" class="btn btn-sm btn-secondary" target="_blank">编辑</a>
                                <button class="btn btn-sm btn-danger" onclick="deleteLandmark({{ landmark.id }})">删除</button>
                            </td>
                        </tr>
                        {% empty %}
                        <tr><td colspan="4" style="text-align:center;color:#888;">暂无地标</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
                {% if landmarks %}
                <div style="margin-top:8px;">
                    <button class="btn btn-sm btn-danger" onclick="batchDeleteLandmarks()">批量删除</button>
                </div>
                {% endif %}
            </div>
        </div>
```

- [ ] **Step 2: Add landmark JavaScript functions**

Find the script section near the end of `settings.html` and add:

```javascript
function deleteLandmark(id) {
    if (!confirm('确定删除此地标？')) return;
    fetch('/settings/landmark/' + id + '/delete/', { method: 'POST', headers: { 'X-CSRFToken': getCookie('csrftoken') } })
        .then(r => r.json()).then(() => location.reload());
}

function batchDeleteLandmarks() {
    const ids = [...document.querySelectorAll('.landmark-check:checked')].map(cb => cb.dataset.id);
    if (ids.length === 0) { alert('请先选择地标'); return; }
    if (!confirm('确定删除选中的 ' + ids.length + ' 个地标？')) return;
    Promise.all(ids.map(id => fetch('/settings/landmark/' + id + '/delete/', { method: 'POST', headers: { 'X-CSRFToken': getCookie('csrftoken') } })))
        .then(() => location.reload());
}

function toggleAllLandmarks(checked) {
    document.querySelectorAll('.landmark-check').forEach(cb => cb.checked = checked);
}

function recalcLandmarks() {
    fetch('/api/landmarks/recalculate/', { method: 'POST', headers: { 'X-CSRFToken': getCookie('csrftoken') } })
        .then(r => r.json()).then(data => {
            if (data.error) { alert(data.error); return; }
            alert('重新分配完成：' + data.assignments + ' 个关联关系');
            location.reload();
        });
}
```

- [ ] **Step 3: Fix zone count display in template**

The landmark table needs to show per-landmark zone counts. The template variable `landmark_zone_counts` is a dict keyed by landmark ID. Update the table cell:

Replace `{{ landmark_zone_counts|default_if_none:0 }}` with:
```html
{{ landmark_zone_counts|default:0 }}
```

Actually, since it's a dict, use:
```django
<td>{{ landmark_zone_counts|dictsort:"0"|default:0 }}</td>
```

No — the simplest way is to use a custom filter or annotate in the view. Since Django templates can't do dict lookups by variable key easily, we should annotate in the view instead. In the `settings_page` view, change the landmarks query to:

```python
from django.db.models import Count
landmarks = Landmark.objects.annotate(zone_count=Count('zone_assignments')).order_by('order', 'name')
```

Then in the template use `{{ landmark.zone_count }}`.

Update the context in `settings_page`:
```python
'landmarks': Landmark.objects.annotate(zone_count=Count('zone_assignments')).order_by('order', 'name'),
```

And remove the separate `landmark_zone_counts` dict. In the template, use `{{ landmark.zone_count }}`.

- [ ] **Step 4: Commit**

```bash
git add internal_server/core/templates/core/settings.html internal_server/core/views.py
git commit -m "feat: add landmark management section to settings page"
```

---

### Task 6: Add landmark data to dashboard view and template

**Files:**
- Modify: `internal_server/core/views.py` (dashboard view, around line 507)
- Modify: `internal_server/core/templates/core/dashboard.html`

- [ ] **Step 1: Add landmark data to dashboard context**

In the `dashboard` view function in `views.py`, add near where `all_plant_names` is computed (around line 828):

```python
from .models import Landmark, ZoneLandmarkAssignment

landmarks_data = []
for lm in Landmark.objects.order_by('order', 'name'):
    landmarks_data.append({
        'id': lm.id,
        'name': lm.name,
        'boundary_points': lm.boundary_points,
        'boundary_color': lm.boundary_color,
        'center': lm.center,
    })

# Build zone→landmark mapping for sidebar filtering
zone_landmark_map = {}
for assignment in ZoneLandmarkAssignment.objects.select_related('landmark').all():
    zone_landmark_map.setdefault(assignment.zone_id, []).append({
        'id': assignment.landmark_id,
        'name': assignment.landmark.name,
    })
```

Add to the context dict:
```python
            'landmarks_json': json.dumps(landmarks_data),
            'landmark_names': [lm['name'] for lm in landmarks_data],
            'zone_landmark_map_json': json.dumps(zone_landmark_map),
```

Also add `landmark_ids` to each zone dict in `zones_list`. Where each zone dict is built (the `zones_list.append({...})` block), add:

```python
            'landmark_ids': [a['id'] for a in zone_landmark_map.get(zone.id, [])],
```

- [ ] **Step 2: Add landmark filter to dashboard sidebar**

In `dashboard.html`, after the plant filter dropdown (after line 750) and before the hierarchical zone list (line 753), add:

```html
                <!-- Landmark filter -->
                <div class="filter-dropdown-wrap">
                    <button type="button" class="filter-dropdown-toggle" id="landmarkDropdownBtn" onclick="toggleLandmarkDropdown()">
                        <span>地标筛选</span>
                        <span class="filter-dropdown-count" id="landmarkFilterCount">全部</span>
                        <span class="filter-dropdown-arrow">▾</span>
                    </button>
                    <div class="filter-dropdown-panel" id="landmarkDropdownPanel">
                        <label class="filter-dropdown-check">
                            <input type="checkbox" id="landmarkSelectAll" checked onchange="toggleAllLandmarks(this.checked)"> 全选
                        </label>
                        {% for name in landmark_names %}
                        <label class="filter-dropdown-check">
                            <input type="checkbox" class="landmark-check" data-landmark="{{ name }}" checked onchange="onLandmarkCheckChange()">
                            <span>{{ name }}</span>
                        </label>
                        {% empty %}
                        <div style="padding:6px 12px;color:#888;font-size:0.85em;">暂无地标</div>
                        {% endfor %}
                    </div>
                </div>
```

- [ ] **Step 3: Add landmark layer toggle to 图层控制**

In `dashboard.html`, in the 图层控制 section (around line 862, after the 水管 toggle), add:

```html
                        <label class="map-layer-item">
                            <input type="checkbox" onchange="toggleLayer('landmarks', this.checked)">
                            <span class="map-layer-checkmark"></span>
                            <span>地标区域</span>
                        </label>
```

- [ ] **Step 4: Add landmarks data script tag**

Near where `zones-data` and `pipelines-data` script tags are defined, add:

```html
<script id="landmarks-data" type="application/json">{{ landmarks_json|safe }}</script>
<script id="zone-landmark-map" type="application/json">{{ zone_landmark_map_json|safe }}</script>
```

- [ ] **Step 5: Add landmark filter JavaScript**

In the dashboard.html script section, add:

```javascript
// Landmark filter
let activeLandmarks = new Set();
let totalLandmarks = 0;
let landmarkFilterTouched = false;

document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.landmark-check').forEach(cb => {
        activeLandmarks.add(cb.dataset.landmark);
        totalLandmarks++;
    });
});

function toggleLandmarkDropdown() {
    const panel = document.getElementById('landmarkDropdownPanel');
    panel.style.display = panel.style.display === 'none' ? '' : 'none';
}

function toggleAllLandmarks(checked) {
    document.querySelectorAll('.landmark-check').forEach(cb => { cb.checked = checked; });
    onLandmarkCheckChange();
}

function onLandmarkCheckChange() {
    landmarkFilterTouched = true;
    activeLandmarks = new Set();
    let count = 0;
    document.querySelectorAll('.landmark-check').forEach(cb => {
        if (cb.checked) { activeLandmarks.add(cb.dataset.landmark); count++; }
    });
    const countEl = document.getElementById('landmarkFilterCount');
    countEl.textContent = count === totalLandmarks ? '全部' : count + '/' + totalLandmarks;
    applyMapFilters();
    filterSidebarByLandmark();
}

function filterSidebarByLandmark() {
    if (!landmarkFilterTouched || totalLandmarks === 0) return;
    const allChecked = activeLandmarks.size === totalLandmarks;
    document.querySelectorAll('.zone-item').forEach(item => {
        if (allChecked) { item.style.display = ''; return; }
        const zoneId = parseInt(item.dataset.zoneId);
        const mapData = JSON.parse(document.getElementById('zone-landmark-map').textContent);
        const lmNames = (mapData[zoneId] || []).map(l => l.name);
        const match = lmNames.some(n => activeLandmarks.has(n));
        item.style.display = match ? '' : 'none';
    });
}

// Close landmark dropdown when clicking outside
document.addEventListener('click', function(e) {
    if (!e.target.closest('#landmarkDropdownBtn') && !e.target.closest('#landmarkDropdownPanel')) {
        const panel = document.getElementById('landmarkDropdownPanel');
        if (panel) panel.style.display = 'none';
    }
});
```

- [ ] **Step 6: Commit**

```bash
git add internal_server/core/views.py internal_server/core/templates/core/dashboard.html
git commit -m "feat: add landmark data, sidebar filter, and layer toggle to dashboard"
```

---

### Task 7: Add landmark rendering to map.js

**Files:**
- Modify: `internal_server/static/js/map.js`
- Modify: `internal_server/staticfiles/js/map.js` (sync copy)

- [ ] **Step 1: Add landmark layer group and rendering**

In `map.js`, after the `labelsLayerGroup` declaration (around line 45), add:

```javascript
    // Landmark overlay layers group
    let landmarksLayerGroup;
```

In `initMap()`, after `labelsLayerGroup = L.layerGroup().addTo(map);` add:

```javascript
        // Initialize landmarks layer group (not added by default — user toggles on)
        landmarksLayerGroup = L.layerGroup();
```

In `setLayerVisibility`, add a new `else if` branch before the closing `};`:

```javascript
        } else if (layer === 'landmarks') {
            if (visible) {
                if (!map.hasLayer(landmarksLayerGroup)) {
                    loadAndRenderLandmarks();
                    map.addLayer(landmarksLayerGroup);
                }
            } else {
                if (map.hasLayer(landmarksLayerGroup)) map.removeLayer(landmarksLayerGroup);
            }
```

Add the landmark loading/rendering functions inside the IIFE:

```javascript
    function loadAndRenderLandmarks() {
        const dataEl = document.getElementById('landmarks-data');
        if (!dataEl) return;
        landmarksLayerGroup.clearLayers();
        try {
            const landmarks = JSON.parse(dataEl.textContent);
            landmarks.forEach(lm => {
                if (!lm.boundary_points || lm.boundary_points.length === 0) return;
                const first = lm.boundary_points[0];
                let rings;
                if (Array.isArray(first) && first.length > 0 && (Array.isArray(first[0]) || first[0]?.lat !== undefined)) {
                    rings = lm.boundary_points;
                } else {
                    rings = [lm.boundary_points];
                }
                rings.forEach(ring => {
                    const latLngs = ring.map(p => {
                        if (Array.isArray(p)) return [p[0], p[1]];
                        if (p.lat !== undefined) return [p.lat, p.lng];
                        return null;
                    }).filter(Boolean);
                    if (latLngs.length >= 3) {
                        L.polygon(latLngs, {
                            color: lm.boundary_color,
                            weight: 2,
                            opacity: 0.6,
                            fillColor: lm.boundary_color,
                            fillOpacity: 0.08,
                            dashArray: '8 4',
                        }).addTo(landmarksLayerGroup);
                    }
                });
                // Label at center
                if (lm.center && lm.center.lat != null) {
                    L.marker([lm.center.lat, lm.center.lng], {
                        interactive: false,
                        icon: L.divIcon({
                            className: 'landmark-label',
                            html: '<span style="font-size:13px;font-weight:600;color:' + lm.boundary_color + ';text-shadow:0 0 4px white,0 0 4px white;">' + lm.name + '</span>',
                            iconSize: null,
                            iconAnchor: [0, 0],
                        })
                    }).addTo(landmarksLayerGroup);
                }
            });
        } catch (e) {}
    }
```

- [ ] **Step 2: Sync to staticfiles/js/map.js**

Copy the modified `static/js/map.js` to `staticfiles/js/map.js`.

- [ ] **Step 3: Commit**

```bash
git add internal_server/static/js/map.js internal_server/staticfiles/js/map.js
git commit -m "feat: add landmark overlay rendering to map"
```

---

### Task 8: Install Shapely and test

**Files:**
- Modify: `requirements.txt` or equivalent (if it exists)

- [ ] **Step 1: Install Shapely**

Run: `pip install shapely`

- [ ] **Step 2: Test the full flow**

1. Open settings page → create a new landmark → draw boundary on map → save
2. Verify landmark appears in the settings table
3. Click "重新分配" → verify assignments are calculated
4. Open dashboard → verify landmark filter dropdown appears
5. Select a landmark in the dropdown → verify sidebar zones filter correctly
6. Toggle "地标区域" in 图层控制 → verify landmark boundaries render on map
7. Untoggle → verify they disappear

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat: complete landmark feature with CRUD, overlap calculation, sidebar filter, and map overlay"
```
