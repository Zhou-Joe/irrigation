"""Shared park geography labels, without irrigation work or asset details."""
from collections import defaultdict

from django.core.cache import cache


def _label(name, points):
    lats, lngs = zip(*points)
    return {
        'name': name,
        'center': [sum(lats) / len(lats), sum(lngs) / len(lngs)],
        'bounds': [[min(lats), min(lngs)], [max(lats), max(lngs)]],
    }


def map_labels():
    from core.models import Zone
    from core.views import get_zone_center, _zone_revision

    key = 'operations:park-geography:v2:' + _zone_revision()
    saved = cache.get(key)
    if saved is not None:
        return saved
    lands, areas = defaultdict(list), defaultdict(list)
    zones = Zone.objects.filter(land__isnull=False).select_related('land').only(
        'name', 'code', 'land__name', 'boundary_source', 'boundary_points', 'dxf_boundary_points')
    for zone in zones.iterator(chunk_size=200):
        center = get_zone_center(zone.active_boundary_points)
        if not center:
            continue
        point = (center['lat'], center['lng'])
        land = zone.land.name.strip()
        name = zone.name.strip()
        if land:
            lands[land].append(point)
        if name and name != land and name != zone.code:
            areas[land, name].append(point)
    result = {
        'region_labels': [_label(name, points) for name, points in sorted(lands.items())],
        'area_labels': [dict(_label(name, points), land=land)
                        for (land, name), points in sorted(areas.items())],
    }
    cache.set(key, result, 300)
    return result
