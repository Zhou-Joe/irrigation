"""A manager curates the receiving team's location access, never source ownership."""
import uuid

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from core.submissions import submission
from .access import audit, browsable_locations, require_member, visible_locations
from .location_filters import matching_locations
from .models import LocationGrant


@login_required
@require_POST
def update(request):
    member=require_member(request,manager=True)
    # Check context before receipt replay, including for already-open clients.
    if request.POST.get('team')!=str(member.team_id):
        return JsonResponse({'success':False,'message':'当前业务团队已变化，请重新打开区域管理。'},status=409)
    return _update(request,member)


@submission('location-team-visibility')
def _update(request,member):
    try:
        action=request.POST.get('action','')
        if action not in ('add','remove'):raise ValueError('请选择加入本团队或移出本团队。')
        scope=request.POST.get('scope','catalog')
        if scope not in ('team','catalog'):raise ValueError('区域视图已变化，请重新打开区域管理。')
        places=browsable_locations(member,request.user).select_related(None).exclude(owner_team=member.team)
        if request.POST.get('all_matching')=='1':
            if scope=='team':
                places=places.filter(pk__in=visible_locations(member.team).values('pk'))
            places=matching_locations(places,member.team,request.POST)
            selected=list(places.values_list('pk',flat=True)[:10001])
        else:
            try:identifiers={uuid.UUID(value) for value in request.POST.getlist('locations')}
            except (ValueError,TypeError,AttributeError):raise ValueError('所选地点编号无效，请重新选择。')
            if not identifiers or len(identifiers)>10000:raise ValueError('每批请选择 1–10000 个其他团队地点。')
            selected=list(places.filter(pk__in=identifiers).values_list('pk',flat=True))
            if len(selected)!=len(identifiers):
                raise ValueError('部分地点不可用，或包含本团队自有地点，请重新选择。')
        if not selected:raise ValueError('当前筛选结果中没有可操作的其他团队地点。')
        if len(selected)>10000:raise ValueError('每批最多操作 10000 个地点，请缩小筛选范围后再试。')
        with transaction.atomic():
            changed=0
            for offset in range(0,len(selected),500):
                batch=selected[offset:offset+500]
                grants=LocationGrant.objects.filter(team=member.team,location_id__in=batch)
                if action=='add':
                    existing=set(grants.values_list('location_id',flat=True))
                    rows=[LocationGrant(location_id=identifier,team=member.team,created_by=request.user)
                          for identifier in batch if identifier not in existing]
                    LocationGrant.objects.bulk_create(rows,ignore_conflicts=True,batch_size=500)
                    changed+=len(rows)
                else:
                    changed+=grants.delete()[0]
            audit(request,member.team,'location.team_visibility.'+action,member.team_id,
                  selected=len(selected),changed=changed,location_ids=[str(identifier) for identifier in selected[:20]])
        message=f'已将 {changed} 个地点加入本团队可见范围。' if action=='add' else f'已将 {changed} 个地点移出本团队可见范围。'
        return JsonResponse({'success':True,'message':message,'count':changed,'selected_count':len(selected),'refresh':True})
    except (ValueError,TypeError,AttributeError) as error:
        return JsonResponse({'success':False,'message':str(error) if isinstance(error,ValueError) else '请检查所选地点。'},status=400)
