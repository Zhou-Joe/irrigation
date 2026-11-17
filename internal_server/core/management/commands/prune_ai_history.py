import json
from django.core.management.base import BaseCommand
from core.ai_history import prune_history


class Command(BaseCommand):
    help = 'Keep only Shanghai-today AI conversations, checkpoints and generated attachments.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--reconcile-dates', action='store_true', help='Restore dates for migrated legacy threads')

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(prune_history(dry_run=options['dry_run'],
            reconcile_dates=options['reconcile_dates']), ensure_ascii=False))
