"""Mark dispatched PM work orders as overdue past their completion window.

A PM task is overdue when a full frequency period has elapsed past its
scheduled_date without completion — i.e. the worker had one whole cycle to do
it and the next occurrence is already due. So the deadline is
``scheduled_date + one period`` (days/weeks/months per the plan's frequency),
not scheduled_date itself. This gives annual tasks ~a year, monthly tasks ~a
month, etc.

Run daily (before generate_pm_workorders) so the completion-tab stats, the
overdue-order list, and the field-worker popup all reflect overdue state.

Usage:
    python manage.py mark_pm_overdue              # run for today
    python manage.py mark_pm_overdue --date 2026-07-15   # run for a specific date
"""

from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import GeneratedWorkOrder


def _deadline(gwo):
    """The completion deadline = scheduled_date + one frequency period."""
    p = gwo.plan
    if p.frequency_unit == 'days':
        return gwo.scheduled_date + timedelta(days=p.frequency_value)
    if p.frequency_unit == 'weeks':
        return gwo.scheduled_date + timedelta(weeks=p.frequency_value)
    if p.frequency_unit == 'months':
        return gwo.scheduled_date + relativedelta(months=p.frequency_value)
    return gwo.scheduled_date


class Command(BaseCommand):
    help = 'Transition dispatched PM work orders past their completion window to overdue.'

    def add_arguments(self, parser):
        parser.add_argument('--date', type=str, default='',
                            help='Run for a specific date (YYYY-MM-DD).')

    def handle(self, *args, **options):
        today = timezone.localdate()
        if options['date']:
            today = date.fromisoformat(options['date'])

        count = 0
        for gwo in (GeneratedWorkOrder.objects
                    .filter(status='dispatched')
                    .select_related('plan')):
            if _deadline(gwo) < today:
                gwo.status = 'overdue'
                gwo.save(update_fields=['status'])
                count += 1
        self.stdout.write(f'mark_pm_overdue for {today}: {count} order(s) → overdue')
