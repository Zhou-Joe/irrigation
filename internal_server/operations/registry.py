"""Canonical irrigation place references, never automatic cross-team grants."""
from django.db import IntegrityError, transaction
from django.db.models import F
from django.db.models.deletion import ProtectedError

from .models import Location, Team


def irrigation_owner(using='default'):
    teams=Team.objects.using(using).filter(business__code='irrigation',legacy_irrigation_access=True,
        active=True,business__active=True)
    return teams.filter(code='irrigation').first() or teams.order_by('pk').first()


def _metadata(zone):
    return {'name':str(zone.name or zone.code or f'区域 {zone.pk}')[:150],
            'code':str(zone.code or '')[:100]}


def sync_irrigation_locations(*,using='default',zone_ids=None):
    """Idempotently register missing zones; existing custom references stay intact.

    The optional subset is used after a normal Zone save. Bulk importers that
    bypass post_save can call this service after their transaction, or run the
    sync_location_registry command. Geometry remains resolved through legacy_zone.
    """
    with transaction.atomic(using=using):
        team=irrigation_owner(using)
        if team is None:return {'created':0,'updated':0}
        Team.objects.using(using).filter(pk=team.pk).update(active=F('active'))
        from core.models import Zone
        zones=Zone.objects.using(using).only('pk','name','code').order_by('pk')
        if zone_ids is not None:zones=zones.filter(pk__in=zone_ids)
        zones=list(zones)
        links={p.legacy_zone_id:p for p in Location.objects.using(using).filter(
            legacy_zone_id__in=[z.pk for z in zones]).only('pk','owner_team_id','legacy_zone_id','name','code','registry_generated')}
        codes=set(Location.objects.using(using).filter(owner_team=team).exclude(code='').values_list('code',flat=True))
        pending=[];updates=[]
        for zone in zones:
            link=links.get(zone.pk)
            if link is not None and (not link.registry_generated or link.owner_team_id!=team.pk):continue
            values=_metadata(zone)
            if link and link.code:codes.discard(link.code)
            if values['code'] in codes:values['code']=''
            if values['code']:codes.add(values['code'])
            if link is None:
                pending.append(Location(owner_team=team,legacy_zone_id=zone.pk,registry_generated=True,**values))
            elif link.name!=values['name'] or link.code!=values['code']:
                link.name=values['name'];link.code=values['code'];updates.append(link)
        # The unique legacy_zone relation handles concurrent registration. A code
        # concurrently claimed by a custom location must never prevent its source
        # irrigation zone from being saved; retry missing references with no code.
        if updates:
            for link in updates:
                try:
                    with transaction.atomic(using=using):
                        Location.objects.using(using).filter(pk=link.pk,registry_generated=True).update(name=link.name,code=link.code)
                except IntegrityError:
                    Location.objects.using(using).filter(pk=link.pk,registry_generated=True).update(name=link.name,code='')
        if pending:Location.objects.using(using).bulk_create(pending,ignore_conflicts=True)
        registered=set(Location.objects.using(using).filter(legacy_zone_id__in=[z.pk for z in zones]).values_list('legacy_zone_id',flat=True))
        missing=[Location(owner_team=team,legacy_zone_id=zone.pk,registry_generated=True,
            name=_metadata(zone)['name'],code='') for zone in zones if zone.pk not in registered]
        if missing:Location.objects.using(using).bulk_create(missing,ignore_conflicts=True)
        final_count=Location.objects.using(using).filter(legacy_zone_id__in=[z.pk for z in zones]).count()
        return {'created':max(0,final_count-len(links)),'updated':len(updates)}


def ensure_irrigation_location(zone,*,using='default'):
    link=Location.objects.using(using).filter(legacy_zone_id=zone.pk).only(
        'pk','registry_generated','name','code').first()
    if link:
        values=_metadata(zone)
        if not link.registry_generated or (link.name==values['name'] and link.code==values['code']):
            return {'created':0,'updated':0}
    return sync_irrigation_locations(using=using,zone_ids=[zone.pk])


def delete_unused_zone_links(zone_ids,*,using='default'):
    """Remove only pristine registry references before an explicit Zone delete.

    Caller should also wrap the subsequent Zone delete in its own transaction.
    Custom places or references used by any team/record/plan remain protected.
    """
    with transaction.atomic(using=using):
        candidates=Location.objects.using(using).filter(legacy_zone_id__in=zone_ids)
        candidates.update(registry_generated=F('registry_generated'))
        links=list(candidates.select_for_update().order_by('pk'))
        for link in links:
            if (not link.registry_generated or link.grants.exists() or link.children.exists() or
                link.pest_records.exists() or link.pest_plans.exists() or link.pest_tasks.exists()):
                raise ValueError('部分区域已有关联地点、团队可见范围或业务记录，请先处理关联后再删除。')
        try:
            count=Location.objects.using(using).filter(pk__in=[link.pk for link in links]).delete()[0]
        except ProtectedError as error:
            raise ValueError('部分区域已被业务资料引用，暂不能删除。') from error
        return count
