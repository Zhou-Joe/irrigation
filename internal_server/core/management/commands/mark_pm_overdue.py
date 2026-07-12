"""Mark dispatched PM work orders as overdue when their scheduled_date passes.

The ``overdue`` status on GeneratedWorkOrder exists in the model but is never
written by the dispatch engine — this command is the sole writer. Run it daily
(before ``generate_pm_workorders``) so that the completion-tab stats, the
overdue-order list, and the field-worker popup all reflect overdue state via
a real DB status rather than an ad-hoc date comparison.

Usage:
    python manage.py mark_pm_overdue              # run for today
    python manage.py mark_pm_overdue --date 2026-07-15   # run for a specific date
"""

from datetime import date

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import GeneratedWorkOrder


class Command(BaseCommand):
    help = 'Transition dispatched PM work orders past their scheduled_date to overdue.'

    def add_arguments(self, parser):
        parser.add_argument('--date', type=str, default='',
                            help='Run for a specific date (YYYY-MM-DD).')

    def handle(self, *args, **options):
        today = timezone.localdate()
        if options['date']:
            today = date.fromisoformat(options['date'])

        qs = GeneratedWorkOrder.objects.filter(
            status='dispatched', scheduled_date__lt=today,
        )
        count = qs.update(status='overdue')
        self.stdout.write(f'mark_pm_overdue for {today}: {count} order(s) → overdue')
