"""Public location geometry for authorized teams, independent of business records."""


def location_map_data(location):
    from core.views import get_zone_center

    boundary = location.boundary
    map_display = 'pin' if location.kind in location.POINT_KINDS else location.map_display
    center = get_zone_center(boundary)
    point = ({'lat': float(location.latitude), 'lng': float(location.longitude)}
             if location.latitude is not None and location.longitude is not None else None)
    if point and (map_display == 'pin' or not center):
        center = point
    return {
        'id': str(location.pk), 'name': location.name, 'code': location.code,
        'kind': location.kind, 'kind_label': location.get_kind_display(),
        'map_display': map_display, 'boundary': boundary, 'center': center,
        'latitude': location.latitude, 'longitude': location.longitude,
        'source': location.boundary_source,
    }
