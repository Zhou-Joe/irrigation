"""Mark dispatched PM work orders as overdue past their completion window.

A PM task is overdue when one full frequency period has elapsed after its
scheduled_date without completion. Advance generation via lead_days does
not shorten this execution window. The deadline day itself is still on time.

Run daily (before generate_pm_workorders) so the completion-tab stats, the
overdue-order list, and the field-worker popup all reflect overdue state.

Usage:
    python manage.py mark_pm_overdue              # run for today
    python manage.py mark_pm_overdue --date 2026-07-15   # run for a specific date
"""

from datetime import date

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.pm_utils import overdue_orders


class Command(BaseCommand):
    help = 'Transition dispatched PM work orders past their completion window to overdue.'

    def add_arguments(self, parser):
        parser.add_argument('--date', type=str, default='',
                            help='Run for a specific date (YYYY-MM-DD).')

    def handle(self, *args, **options):
        today = timezone.localdate()
        if options['date']:
            today = date.fromisoformat(options['date'])

        count = overdue_orders(today).filter(status='dispatched').update(status='overdue')
        self.stdout.write(f'mark_pm_overdue for {today}: {count} order(s) → overdue')
