"""Shared PM lifecycle rules for dispatch, management and skip actions."""

from datetime import timedelta

from dateutil.relativedelta import relativedelta
from django.utils import timezone

from .models import GeneratedWorkOrder, Crew, Worker


def validate_schedule(plan):
    if plan.frequency_value < 1 or plan.frequency_unit not in ('days', 'weeks', 'months'):
        raise ValueError('PM frequency must be positive and use days/weeks/months')


def occurrence(plan, index):
    """Keep the original anchor day; short months clamp without losing a cycle."""
    validate_schedule(plan)
    if plan.frequency_unit == 'months':
        return plan.start_date + relativedelta(months=plan.frequency_value * index)
    days = plan.frequency_value * (7 if plan.frequency_unit == 'weeks' else 1)
    return plan.start_date + timedelta(days=days * index)


def cycle_index(plan, day):
    validate_schedule(plan)
    if day < plan.start_date:
        return -1
    if plan.frequency_unit != 'months':
        days = plan.frequency_value * (7 if plan.frequency_unit == 'weeks' else 1)
        return (day - plan.start_date).days // days
    months = (day.year - plan.start_date.year) * 12 + day.month - plan.start_date.month
    index = months // plan.frequency_value
    if occurrence(plan, index) > day:
        index -= 1
    return index


def next_due(plan, today):
    index = cycle_index(plan, today)
    if index < 0:
        return plan.start_date
    current = occurrence(plan, index)
    return current if current == today else occurrence(plan, index + 1)


def plan_zones(plan):
    level = plan.job_plan.asset_level
    if level == 'sat':
        return list(plan.satellite.zones.all()) if plan.satellite_id else []
    if level == 'ccu':
        return list(plan.patch.zones.all()) if plan.patch_id else []
    return list(plan.zones.all())


def matching_crew(plan, zones):
    """Require one responsible crew covering the entire asset scope."""
    if plan.crew_id:
        return (plan.crew, '') if plan.crew.active else (None, '负责班组已停用')
    patch_id = (plan.patch_id if plan.job_plan.asset_level == 'ccu' else
                plan.satellite.patch_id if plan.job_plan.asset_level == 'sat' and plan.satellite_id else None)
    if patch_id:
        crews = list(Crew.objects.filter(active=True, patches=patch_id).distinct())
        if len(crews) == 1:
            return crews[0], ''
        if len(crews) > 1:
            return None, '多个班组负责同一CCU，请手动指定'
    lands = {z.land_id for z in zones}
    if not lands or None in lands:
        return None, '区域缺少Land归属，无法匹配班组'
    crews = list(Crew.objects.filter(active=True, lands__in=lands).prefetch_related('lands').distinct())
    matches = [c for c in crews if lands <= {land.id for land in c.lands.all()}]
    if len(matches) == 1:
        return matches[0], ''
    return None, ('多个班组覆盖全部区域，请手动指定' if len(matches) > 1 else
                  '没有班组覆盖全部区域，请手动指定')


def crew_worker(crew):
    if not crew or not crew.active:
        return None
    if crew.leader_id and crew.leader.active:
        return crew.leader
    return crew.members.filter(active=True).order_by('id').first()


def visible_orders(user):
    """Central permission scope for PM details, extensions and completion."""
    from django.db.models import Q
    from .role_utils import is_admin, get_worker_for_user
    if is_admin(user):
        return GeneratedWorkOrder.objects.all()
    worker = get_worker_for_user(user)
    if not worker or not worker.active:
        return GeneratedWorkOrder.objects.none()
    crews = Crew.objects.filter(Q(leader=worker) | Q(members=worker)).values('pk')
    return GeneratedWorkOrder.objects.filter(Q(crew_id__in=crews) | Q(crew__isnull=True, worker=worker))


def order_deadline(gwo):
    return gwo.deadline or completion_deadline(gwo.plan, gwo.scheduled_date)


def completion_deadline(plan, scheduled_date):
    """One execution cycle after the scheduled date, regardless of lead time."""
    if plan.frequency_value < 1:
        raise ValueError('frequency_value must be at least 1')
    if plan.frequency_unit == 'days':
        return scheduled_date + timedelta(days=plan.frequency_value)
    if plan.frequency_unit == 'weeks':
        return scheduled_date + timedelta(weeks=plan.frequency_value)
    if plan.frequency_unit == 'months':
        return scheduled_date + relativedelta(months=plan.frequency_value)
    raise ValueError(f'Unknown PM frequency unit: {plan.frequency_unit}')


def is_overdue(gwo, today=None):
    """Completed/skipped orders are closed; the deadline day is still on time."""
    today = today if today is not None else timezone.localdate()
    if gwo.status not in ('dispatched', 'overdue'):
        return False
    try:
        return order_deadline(gwo) < today
    except ValueError:
        # Invalid schedules are reported by dispatch; never skip them early.
        return False


def overdue_orders(today=None):
    """Use calendar months in Python so SQLite and other backends agree."""
    today = today if today is not None else timezone.localdate()
    candidates = GeneratedWorkOrder.objects.filter(
        status__in=['dispatched', 'overdue'],
        scheduled_date__lt=today,
    )
    ids = []
    for gwo in candidates.select_related('plan').only(
        'id', 'scheduled_date', 'status', 'deadline', 'plan',
        'plan__frequency_value', 'plan__frequency_unit',
    ).iterator():
        if is_overdue(gwo, today):
            ids.append(gwo.pk)
    return candidates.filter(pk__in=ids)


def completion_stats(plans, period, today, period_window):
    """Aggregate each plan in its own cycle, including staggered anchors."""
    groups, windows = {}, {}
    offset = {'current': 0, 'prev': -1, 'prev2': -2}.get(period, 0)
    units = {'days': '日', 'weeks': '周', 'months': '月'}
    for plan in plans:
        group = groups.setdefault(plan.job_plan_id, {
            'name': plan.job_plan.name, 'total': 0, 'completed': 0,
            'dispatched': 0, 'overdue': 0, 'skipped': 0, 'frequencies': set(),
        })
        group['frequencies'].add(f'每{plan.frequency_value}{units.get(plan.frequency_unit, plan.frequency_unit)}')
        if period == 'all':
            windows[plan.pk] = (None, None)
        else:
            start, end, _ = period_window(plan.frequency_value, plan.frequency_unit, plan.start_date, offset, today)
            windows[plan.pk] = (start, end) if start is not None else None
    orders = GeneratedWorkOrder.objects.filter(plan_id__in=windows).select_related('plan')
    for gwo in orders.iterator():
        window = windows[gwo.plan_id]
        if window is None or (window[0] is not None and not window[0] <= gwo.scheduled_date <= window[1]):
            continue
        group = groups[gwo.plan.job_plan_id]
        group['total'] += 1
        group['completed'] += gwo.status == 'completed'
        group['dispatched'] += gwo.status in ('dispatched', 'overdue')
        group['skipped'] += gwo.status == 'skipped'
        group['overdue'] += is_overdue(gwo, today)
    for group in groups.values():
        frequencies = group.pop('frequencies')
        group['freq_label'] = '、'.join(sorted(frequencies))
        group['period_label'] = '全部' if period == 'all' else '按各计划周期'
        group['rate'] = round(group['completed'] * 100 / group['total']) if group['total'] else 0
    return sorted(groups.values(), key=lambda g: g['name'])
