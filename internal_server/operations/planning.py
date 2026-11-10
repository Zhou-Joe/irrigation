"""Pest dispatch uses its own rotation pools and cannot move irrigation schedules."""
import calendar
from datetime import date, timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .access import visible_locations
from .models import Membership, PestMaintenancePlan, PestTask


def period(day,value,unit):
    if unit in ('days','weeks'):
        return day+timedelta(days=value*(7 if unit=='weeks' else 1))
    months=day.year*12+day.month-1+value*(12 if unit=='years' else 1)
    year,month=divmod(months,12);month+=1
    return date(year,month,min(day.day,calendar.monthrange(year,month)[1]))


def occurrence(plan,index):
    return period(plan.anchor_date,plan.frequency_value*index,plan.frequency_unit)


def next_occurrence(plan,cycle):
    if plan.frequency_unit in ('days','weeks'):
        days=plan.frequency_value*(7 if plan.frequency_unit=='weeks' else 1)
        index=(cycle-plan.anchor_date).days//days
    else:
        months=plan.frequency_value*(12 if plan.frequency_unit=='years' else 1)
        index=((cycle.year-plan.anchor_date.year)*12+cycle.month-plan.anchor_date.month)//months
    return occurrence(plan,index+1)


def eligible_members(team):
    return Membership.objects.filter(team=team,active=True,user__is_active=True,
        role__in=['manager','field']).select_related('user').order_by('user__username')


def task_scope(request,member):
    qs=PestTask.objects.filter(team=member.team).select_related('plan','location','assignee','report','catalog')
    if member.role!='manager' and not request.user.is_superuser:qs=qs.filter(assignee=request.user)
    return qs


def generate_due(*,team=None,today=None,dry=False):
    today=today or timezone.localdate();result={'generated':0,'plans':0,'errors':[]}
    plans=PestMaintenancePlan.objects.filter(active=True,team__active=True,
        team__business__active=True,team__business__code='pest-control',next_cycle__lte=today)
    if team:plans=plans.filter(team=team)
    for identifier in plans.values_list('pk',flat=True):
        try:
            with transaction.atomic():
                if not dry:PestMaintenancePlan.objects.filter(pk=identifier).update(active=F('active'))
                plan=PestMaintenancePlan.objects.select_related('team__business').get(pk=identifier)
                if not plan.active or plan.next_cycle>today:continue
                places=list(visible_locations(plan.team).select_related(None).filter(pest_plans=plan).order_by('name','pk'))
                users=list(eligible_members(plan.team).filter(user__pest_plans=plan).values_list('user_id',flat=True))
                if not places or not users:
                    result['errors'].append(f'{plan.name}：缺少可用地点或负责成员。');continue
                cycle=plan.next_cycle;cycles=0;created=0
                while cycle<=today and cycles<12:
                    following=next_occurrence(plan,cycle);length=(following-cycle).days
                    existing=set(plan.tasks.filter(cycle_start=cycle).values_list('location_id',flat=True))
                    pending=[]
                    for index,location in enumerate(places):
                        if location.pk in existing:continue
                        scheduled=cycle+timedelta(days=index*length//len(places))
                        pending.append(PestTask(team=plan.team,plan=plan,title=plan.name,catalog=plan.catalog,
                            selections=plan.selections,location=location,location_label=location.name,
                            assignee_id=users[(index+cycles)%len(users)],cycle_start=cycle,
                            scheduled_date=scheduled,deadline=period(scheduled,plan.frequency_value,plan.frequency_unit)))
                    created+=len(pending)
                    if not dry:PestTask.objects.bulk_create(pending)
                    cycle=following;cycles+=1
                if not dry:
                    plan.next_cycle=cycle;plan.save(update_fields=['next_cycle','updated_at'])
                result['generated']+=created;result['plans']+=1
                if cycle<=today:result['errors'].append(f'{plan.name}：已补发 12 个周期，其余将在下次派发继续。')
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Pest dispatch failed for plan %s',identifier)
            result['errors'].append(f'计划 {identifier} 派发失败，请检查配置后重试。')
    return result
