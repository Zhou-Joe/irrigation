# Landmarks (地标) Feature Design

## Overview

Add a new "Landmark" (地标) entity — a user-friendly place name with drawn boundaries on the map. Zones are automatically assigned to landmarks based on boundary overlap. Landmarks provide a new filtering dimension in the dashboard sidebar.

Landmarks are **independent** of the existing Region → Patch → Zone hierarchy.

## Data Model

### Landmark model

```python
class Landmark(models.Model):
    name = models.CharField(max_length=255, unique=True)
    boundary_points = models.JSONField(default=list)  # multi-polygon, same format as Zone
    boundary_color = models.CharField(max_length=7, default='#E8590C')
    center = models.JSONField(null=True, blank=True)  # {lat, lng}
    area_sqm = models.FloatField(null=True, blank=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

### Zone ↔ Landmark relationship (M2M through table)

```python
class ZoneLandmarkAssignment(models.Model):
    zone = models.ForeignKey(Zone, on_delete=models.CASCADE, related_name='landmark_assignments')
    landmark = models.ForeignKey(Landmark, on_delete=models.CASCADE, related_name='zone_assignments')
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('zone', 'landmark')
```

The M2M is through an explicit table so we can track when assignments were calculated. Zone gets a convenience property `zone.landmarks` via the relationship.

## Boundary Overlap Calculation

Uses Shapely for polygon intersection detection.

- For each landmark, check every zone's boundary against the landmark boundary
- A zone is assigned to a landmark if any ring of the zone's boundary intersects any ring of the landmark boundary (including full containment)
- Algorithm: convert JSON boundary_points → Shapely Polygon → `zone_poly.intersects(landmark_poly)`
- Handle multi-polygon format (list of rings) by creating MultiPolygon or testing ring-by-ring

**Calculation is triggered on demand** via a "重新分配" button in the settings page. It is NOT run automatically on every zone/landmark save (too expensive). Users recalculate when they:
- Create a new landmark
- Create a new zone
- Modify an existing landmark or zone boundary

## Settings Page (区域管理)

### Landmark management section — below the zone table

- **Landmark table**: columns for name, boundary color, zone count, area
- **CRUD**: add/edit/delete landmarks inline (similar pattern to existing zone management)
- **Draw boundary**: opens a map drawing interface (reuse the zone_batch_draw pattern adapted for landmarks)
- **"重新分配" button**: recalculates all zone↔landmark assignments, shows a toast with count of assignments updated
- Each landmark row shows how many zones are assigned to it

## Dashboard Map

### Layer control addition

New toggle "地标区域" in the 图层控制 panel, **off by default**.

When enabled:
- Draw landmark boundaries as semi-transparent colored overlays on the map
- Show landmark name labels at the landmark center
- Style: dashed boundary line, very light fill (opacity ~0.1)

### Sidebar filter

Multi-select dropdown for landmarks (similar to the existing plant filter dropdown):
- Placed as the first filter in the sidebar, or right below the search box
- When one or more landmarks are selected, only zones belonging to those landmarks are shown in the sidebar and highlighted on the map
- "全部" option to clear the filter
- Zones not assigned to any landmark are shown when no filter is active, or hidden when any landmark filter is active

## Files to modify/create

| File | Action |
|------|--------|
| `core/models.py` | Add `Landmark` and `ZoneLandmarkAssignment` models |
| `core/migrations/004X_...py` | New migration |
| `core/views.py` | Add landmark CRUD views, recalculate endpoint |
| `core/urls.py` | Add landmark URLs |
| `core/templates/core/settings.html` | Add landmark management section |
| `core/templates/core/landmark_draw.html` | New — boundary drawing page for landmarks |
| `core/templates/core/dashboard.html` | Add landmark filter in sidebar, layer toggle, map rendering |
| `static/js/map.js` | Add landmark layer rendering, filter logic |

## Out of scope

- No automatic recalculation on zone/landmark save (manual button only)
- No landmark boundaries shown on the zone detail page
- No import/export for landmarks (can add later)
- No nesting/hierarchy between landmarks (flat list)
