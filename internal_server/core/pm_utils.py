"""Shared PM lifecycle rules for dispatch, management and skip actions."""

from datetime import timedelta

from dateutil.relativedelta import relativedelta
from django.utils import timezone

from .models import GeneratedWorkOrder


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
        return completion_deadline(gwo.plan, gwo.scheduled_date) < today
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
        'id', 'scheduled_date', 'status', 'plan',
        'plan__frequency_value', 'plan__frequency_unit',
    ).iterator():
        if is_overdue(gwo, today):
            ids.append(gwo.pk)
    return candidates.filter(pk__in=ids)
