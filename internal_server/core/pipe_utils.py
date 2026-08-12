"""Geometry helpers for the pipeline feature.

The project has no GeoDjango (zones store boundaries as plain JSONField arrays
of {lat,lng}). These helpers do polyline/polygon intersection in Python so a
pipeline can auto-discover which zones its ``line_points`` cross, without a
manual checkbox hunt across 2500+ zones.

Coordinate convention: every point is a ``(lat, lng)`` tuple. The geometry
primitives (point-in-ring ray casting, segment-segment orientation test) are
coordinate-system agnostic, so lat/lng works directly — no projection needed
for pure crossing detection. ``buffer_meters`` only widens the candidate bbox
prefilter, it does not inflate polygons (true polygon inflation is expensive
and the grazing-edge case is rare enough to ignore).
"""

from __future__ import annotations

import math


# ── point normalization ────────────────────────────────────────────────
def _to_latlng(p):
    """Normalize a single point to a ``(lat, lng)`` tuple of floats, or None.

    Accepts ``{'lat':..,'lng':..}``, ``{'latitude':..,'longitude':..}``,
    or ``[lat, lng]`` list forms.
    """
    if isinstance(p, dict):
        if 'lat' in p:
            return (float(p['lat']), float(p.get('lng', p.get('longitude', 0))))
        if 'latitude' in p:
            return (float(p['latitude']), float(p.get('longitude', 0)))
    elif isinstance(p, (list, tuple)) and len(p) >= 2:
        try:
            return (float(p[0]), float(p[1]))
        except (TypeError, ValueError):
            return None
    return None


def _is_point(p):
    """True if ``p`` looks like a single point (not a ring/group container)."""
    if isinstance(p, dict):
        return 'lat' in p or 'latitude' in p
    if isinstance(p, (list, tuple)) and len(p) >= 2:
        return isinstance(p[0], (int, float))
    return False


def flatten_rings(pts):
    """Flatten any supported boundary format into a list of rings.

    Each ring is a list of ``(lat, lng)`` tuples with >= 3 points. Handles:
      * single ring: ``[{lat,lng}, ...]``
      * flat multi-ring: ``[[outer...], [hole...]]``  (pts[0] is a list of points)
      * nested multi-group: ``[[[outer...],[hole...]], [[outer2...]]]``

    Mirrors the format detection in ``Zone._recalc_area`` (models.py:251-289).
    """
    if not pts:
        return []
    rings = []
    first = pts[0]

    if _is_point(first):
        ring = [_to_latlng(p) for p in pts]
        ring = [r for r in ring if r]
        if len(ring) >= 3:
            rings.append(ring)
        return rings

    if isinstance(first, list) and len(first) > 0:
        inner = first[0]
        if _is_point(inner):
            # flat multi-ring: [outer, hole1, hole2, ...]
            for ring_pts in pts:
                ring = [_to_latlng(p) for p in ring_pts]
                ring = [r for r in ring if r]
                if len(ring) >= 3:
                    rings.append(ring)
        elif isinstance(inner, list):
            # nested multi-group: [[outer, hole], [outer2, ...]]
            for group in pts:
                for ring_pts in group:
                    ring = [_to_latlng(p) for p in ring_pts]
                    ring = [r for r in ring if r]
                    if len(ring) >= 3:
                        rings.append(ring)
    return rings


# ── geometry primitives (work in raw lat/lng) ──────────────────────────
def _point_in_ring(lat, lng, ring):
    """Ray-casting point-in-polygon. Ray cast in +lng direction at height ``lat``.

    ``ring`` is a list of ``(lat, lng)`` tuples (open or closed — closing
    handled implicitly by wrapping the index).
    """
    n = len(ring)
    inside = False
    j = n - 1
    for i in range(n):
        yi, xi = ring[i][0], ring[i][1]
        yj, xj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat):
            # x (lng) where edge crosses the horizontal line y (lat) = lat
            denom = (yj - yi)
            if denom != 0:
                x_int = (xj - xi) * (lat - yi) / denom + xi
                if lng < x_int:
                    inside = not inside
        j = i
    return inside


def _orient(a, b, c):
    """Orientation of triplet (a,b,c) in (lat,lng) space. >0 / <0 / 0."""
    return (b[1] - a[1]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[1] - a[1])


def _on_segment(a, b, p):
    """Given p is collinear with (a,b), is it within the segment bounds?"""
    return (min(a[0], b[0]) - 1e-9 <= p[0] <= max(a[0], b[0]) + 1e-9 and
            min(a[1], b[1]) - 1e-9 <= p[1] <= max(a[1], b[1]) + 1e-9)


def _segments_intersect(p1, p2, p3, p4):
    """Do segment (p1,p2) and segment (p3,p4) intersect? Each p = (lat,lng)."""
    d1 = _orient(p3, p4, p1)
    d2 = _orient(p3, p4, p2)
    d3 = _orient(p1, p2, p3)
    d4 = _orient(p1, p2, p4)
    if ((d1 > 0 > d2) or (d1 < 0 < d2)) and ((d3 > 0 > d4) or (d3 < 0 < d4)):
        return True
    # Collinear / touching cases — treat as crossing (rare, safe side).
    if abs(d1) < 1e-9 and _on_segment(p3, p4, p1):
        return True
    if abs(d2) < 1e-9 and _on_segment(p3, p4, p2):
        return True
    if abs(d3) < 1e-9 and _on_segment(p1, p2, p3):
        return True
    if abs(d4) < 1e-9 and _on_segment(p1, p2, p4):
        return True
    return False


def _seg_intersection(p1, p2, p3, p4):
    """Exact intersection point of segment (p1,p2) with segment (p3,p4), or None.

    Each p = (lat, lng). Returns (lat, lng) where the two infinite lines cross,
    only if it lies within both segments (small epsilon). Used to place a valve
    exactly where a pipe crosses a zone boundary (distinct per zone).
    """
    x1, y1 = p1[0], p1[1]
    x2, y2 = p2[0], p2[1]
    x3, y3 = p3[0], p3[1]
    x4, y4 = p4[0], p4[1]
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-18:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom
    eps = 1e-9
    if (-eps <= t <= 1 + eps) and (-eps <= u <= 1 + eps):
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    return None


def _ring_bbox(ring):
    """(min_lat, max_lat, min_lng, max_lng) of a ring."""
    lats = [p[0] for p in ring]
    lngs = [p[1] for p in ring]
    return min(lats), max(lats), min(lngs), max(lngs)


def _bboxes_overlap(a, b):
    """a, b = (min_lat, max_lat, min_lng, max_lng)."""
    return not (a[1] < b[0] or a[0] > b[1] or a[3] < b[2] or a[2] > b[3])


# ── main entry point ───────────────────────────────────────────────────
def detect_crossed_zones(line_points, buffer_meters=20, zone_qs=None):
    """Return the list of Zone ids whose boundary the polyline crosses/enters.

    Two-step strategy to stay fast across ~2500 zones:
      1) Compute the polyline's bbox, widen it by ``buffer_meters`` (converted
         to degrees). Prefilter zones whose ring bbox does not overlap → most
         are skipped cheaply.
      2) For each surviving zone, per ring: test if any polyline vertex lies
         inside the ring, or any polyline segment intersects any ring edge.

    ``zone_qs`` lets the caller pass a pre-filtered/annotated queryset
    (e.g. only active zones); defaults to all zones with non-empty boundary.
    """
    from .models import Zone

    line = [_to_latlng(p) for p in (line_points or [])]
    line = [p for p in line if p]
    if len(line) < 2:
        return []

    lats = [p[0] for p in line]
    lngs = [p[1] for p in line]
    # 1 deg lat ≈ 111.32 km; for lng it shrinks with cos(lat), but using the
    # lat approximation for both is conservative (slightly wider lng buffer).
    buf_deg = buffer_meters / 111000.0
    line_bbox = (min(lats) - buf_deg, max(lats) + buf_deg,
                 min(lngs) - buf_deg, max(lngs) + buf_deg)

    line_segs = list(zip(line[:-1], line[1:]))

    if zone_qs is None:
        zone_qs = Zone.objects.exclude(boundary_points=[])
    # Only fetch the columns we need; active_boundary_points handles source switch.
    zone_qs = zone_qs.only('id', 'boundary_points', 'dxf_boundary_points', 'boundary_source')

    crossed = []
    for z in zone_qs:
        rings = flatten_rings(z.active_boundary_points)
        if not rings:
            continue
        hit = False
        for ring in rings:
            r_bbox = _ring_bbox(ring)
            if not _bboxes_overlap(line_bbox, r_bbox):
                continue
            # (a) any polyline vertex inside ring?
            for (lat, lng) in line:
                if _point_in_ring(lat, lng, ring):
                    hit = True
                    break
            if hit:
                break
            # (b) any polyline segment crosses any ring edge?
            n = len(ring)
            for s_a, s_b in line_segs:
                for i in range(n):
                    r_a = ring[i]
                    r_b = ring[(i + 1) % n]
                    if _segments_intersect(s_a, s_b, r_a, r_b):
                        hit = True
                        break
                if hit:
                    break
            if hit:
                break
        if hit:
            crossed.append(z.id)

    return crossed


def _center_on_line_in_zone(line, rings, sample_step_m=3.0):
    """Point on the polyline that sits centered inside the zone (not on its edge).

    Densifies the line to ~``sample_step_m`` spacing, keeps the sampled points
    that fall inside any ring, and returns the median one (middle of the
    in-zone stretch). Falls back to None when no part of the line is inside
    (e.g. it only grazes a corner) — callers then use a boundary intersection.
    """
    pts = []
    for i in range(len(line) - 1):
        a = line[i]
        b = line[i + 1]
        dlat = (b[0] - a[0]) * 111320.0
        dlng = (b[1] - a[1]) * 111320.0 * math.cos(math.radians(a[0]))
        dist_m = math.sqrt(dlat * dlat + dlng * dlng)
        n = max(1, int(dist_m / sample_step_m))
        for k in range(n):
            t = k / n
            pts.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
    pts.append(line[-1])
    inside = [p for p in pts if any(_point_in_ring(p[0], p[1], r) for r in rings)]
    if not inside:
        return None
    return inside[len(inside) // 2]


def detect_valve_anchors(line_points, buffer_meters=20):
    """For each zone the polyline crosses, return a valve anchor on the line.

    Returns ``[{zone_id, zone_name, zone_code, station_id, point:[{lat,lng}]}]``
    — one entry per crossed zone. The anchor point is the **first line vertex
    inside the zone** (so it always sits exactly on the drawn pipe); if the
    line only grazes the boundary with no vertex inside, it falls back to the
    midpoint of the first segment that intersects a ring edge. ``station_id``
    is pre-linked from the zone's ``maxicom_runtime`` (its Maxicom station)
    so runtime data shows up without manual pairing.

    This powers the "auto-generate valves from the drawn line" UX: draw the
    pipe, generate one valve per crossed zone, then drag to fine-tune.
    """
    from .models import Zone

    line = [_to_latlng(p) for p in (line_points or [])]
    line = [p for p in line if p]
    if len(line) < 2:
        return []

    crossed_ids = detect_crossed_zones(line_points, buffer_meters=buffer_meters)
    if not crossed_ids:
        return []
    zones = {z.id: z for z in Zone.objects.filter(id__in=crossed_ids)}

    line_segs = list(zip(line[:-1], line[1:]))
    out = []
    for zid in crossed_ids:
        z = zones.get(zid)
        if not z:
            continue
        rings = flatten_rings(z.active_boundary_points)
        if not rings:
            continue
        anchor = None
        # (a) Primary: the point on the line centered inside the zone (median of
        # the in-zone stretch) — so the valve sits in the middle of the zone's
        # served segment, not on its boundary. None when the line only grazes.
        anchor = _center_on_line_in_zone(line, rings)
        # (b) Fallback: exact entry point where the line first crosses this
        #    zone's boundary. Per-zone distinct (each zone's edge is elsewhere)
        #    so adjacent zones don't stack on the same spot.
        if not anchor:
            for s_a, s_b in line_segs:
                for ring in rings:
                    n = len(ring)
                    for i in range(n):
                        ipt = _seg_intersection(s_a, s_b, ring[i], ring[(i + 1) % n])
                        if ipt:
                            anchor = ipt
                            break
                    if anchor:
                        break
                if anchor:
                    break
        if not anchor:
            continue
        # Pre-link the zone's Maxicom station (first one in maxicom_runtime).
        station_id = None
        mr = z.maxicom_runtime
        if mr:
            station_id = mr[0] if isinstance(mr, list) else None
        out.append({
            'zone_id': z.id,
            'zone_name': z.name,
            'zone_code': z.code,
            'station_id': station_id,
            # Zone carries its solenoid valve size in INCHES (0.5/1/1.5/2 —
            # standard irrigation valve sizes). PipeValve.diameter is in mm,
            # so convert inches × 25.4 (1.5" → 38.1mm).
            'diameter': round(z.solenoid_valve_size * 25.4, 1) if z.solenoid_valve_size else None,
            'point': [{'lat': round(anchor[0], 6), 'lng': round(anchor[1], 6)}],
        })
    return out
