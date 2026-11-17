"""Shared park geography labels, without irrigation work or asset details."""
from collections import defaultdict
from django.core.cache import cache


def region_labels():
    from core.models import Zone
    from core.views import get_zone_center, _zone_revision
    key='pest:region-labels:'+str(_zone_revision())
    saved=cache.get(key)
    if saved is not None:
        return saved
    groups=defaultdict(list)
    for zone in Zone.objects.select_related('land').filter(land__isnull=False):
        center=get_zone_center(zone.active_boundary_points)
        if center:
            groups[zone.land.name].append(center)
    result=[{'name':name,'center':[sum(p['lat'] for p in points)/len(points),
                                 sum(p['lng'] for p in points)/len(points)]}
            for name,points in sorted(groups.items())]
    cache.set(key,result,300)
    return result
