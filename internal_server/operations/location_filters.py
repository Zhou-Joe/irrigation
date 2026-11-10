"""One set of location filters for the list, map and bulk-selection boundary."""
from django.db.models import BooleanField, Case, Exists, F, OuterRef, Q, Value, When

from .models import Location, LocationGrant


def filter_values(params):
    kind=params.get('kind','')
    ownership=params.get('ownership','all')
    positioned=params.get('positioned','all')
    source_team=params.get('source_team','all')
    visibility=params.get('visibility','all')
    return {
        'query':params.get('q','').strip()[:150],
        'selected_kind':kind if kind in dict(Location.KINDS) else 'all',
        'selected_ownership':ownership if ownership in ('all','owned','shared') else 'all',
        'selected_positioned':positioned if positioned in ('all','yes','no') else 'all',
        'selected_source_team':source_team if source_team.isdecimal() else 'all',
        'selected_visibility':visibility if visibility in ('all','visible','hidden') else 'all',
    }


def with_team_visibility(places,team):
    grants=LocationGrant.objects.filter(location_id=OuterRef('pk'),team=team)
    return places.annotate(is_team_visible=Case(When(owner_team=team,then=Value(True)),
        default=Exists(grants),output_field=BooleanField()))


def positioned_ids(places):
    """Match map_data's effective-boundary/point resolver, including DXF fallback.

    A non-empty JSON document is not necessarily a usable boundary. Fetch only
    geometry columns for legacy locations without a usable point; do not load
    complete Zone models, remarks, histories or any business data for counts.
    """
    from core.views import get_zone_center

    points=places.filter(latitude__gte=-90,latitude__lte=90,longitude__gte=-180,longitude__lte=180)
    result=set(points.values_list('pk',flat=True))
    legacy=places.exclude(pk__in=result).filter(legacy_zone__isnull=False)
    # Read one geometry per location, not both often-large manual and CAD
    # profiles. Only an empty active DXF needs a second, manual-fallback query.
    legacy=legacy.annotate(_position_boundary=Case(
        When(legacy_zone__boundary_source='dxf',then=F('legacy_zone__dxf_boundary_points')),
        default=F('legacy_zone__boundary_points')))
    fallback=[]
    for identifier,source,active in legacy.values_list('pk','legacy_zone__boundary_source','_position_boundary').iterator():
        if source=='dxf' and not active:fallback.append(identifier)
        elif get_zone_center(active) is not None:result.add(identifier)
    if fallback:
        for identifier,manual in places.filter(pk__in=fallback).values_list('pk','legacy_zone__boundary_points').iterator():
            if get_zone_center(manual) is not None:result.add(identifier)
    return result


def matching_locations(places,team,params,*,positioned=None):
    values=filter_values(params)
    query=values['query']
    if query:places=places.filter(Q(name__icontains=query)|Q(code__icontains=query)|Q(legacy_zone__code__icontains=query))
    if values['selected_kind']!='all':places=places.filter(kind=values['selected_kind'])
    if values['selected_ownership']=='owned':places=places.filter(owner_team=team)
    elif values['selected_ownership']=='shared':places=places.exclude(owner_team=team)
    if values['selected_source_team']!='all':places=places.filter(owner_team_id=int(values['selected_source_team']))
    if values['selected_visibility']!='all':
        places=with_team_visibility(places,team).filter(is_team_visible=values['selected_visibility']=='visible')
    state=values['selected_positioned']
    if state!='all':
        ids=positioned_ids(places) if positioned is None else positioned
        places=places.filter(pk__in=ids) if state=='yes' else places.exclude(pk__in=ids)
    return places
