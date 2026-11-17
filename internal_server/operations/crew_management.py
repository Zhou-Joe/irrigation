"""Use the shared crew editor with workers and places in the active business."""
from django.db.models import Q
from core.models import Worker, Land, Patch
from .access import visible_locations
from .administration import audience_users, management_team


def options(request):
    team=management_team(request)
    workers=Worker.objects.filter(active=True).filter(Q(user__in=audience_users(request))|Q(user__isnull=True) if team is None else Q(user__team_memberships__team=team,user__team_memberships__active=True))
    return {'workers':workers.distinct().order_by('full_name'),
            'lands':Land.objects.order_by('order','name') if team is None else Land.objects.none(),
            'patches':Patch.objects.filter(code__regex=r'^CCU[0-9]+$').order_by('code') if team is None else Patch.objects.none(),
            'locations':visible_locations(team) if team else [],'team':team}


def selections(request):
    allowed=options(request);result={}
    leader=request.POST.get('leader') or None
    if leader and not allowed['workers'].filter(pk=leader).exists():raise ValueError('组长不属于当前业务。')
    for key in ('members','lands','patches','locations'):
        values=set(request.POST.getlist(key))
        source=allowed['workers'] if key=='members' else allowed[key]
        valid={str(value) for value in source.values_list('pk',flat=True)} if hasattr(source,'values_list') else set()
        if values-valid:raise ValueError('班组成员或负责地点不属于当前业务。')
        result[key]=values
    result['leader']=leader
    return result
