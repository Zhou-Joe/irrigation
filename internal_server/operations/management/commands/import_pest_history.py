import json

from django.core.management.base import BaseCommand, CommandError

from operations.history_import import import_history
from operations.models import Team


class Command(BaseCommand):
    help = 'Validate a private historical bird-collision manifest; use --apply to create records.'

    def add_arguments(self, parser):
        parser.add_argument('manifest')
        parser.add_argument('--team', required=True, help='Destination pest team code.')
        parser.add_argument('--apply', action='store_true', help='Apply after validation; otherwise dry-run only.')

    def handle(self, *args, **options):
        try:
            team = Team.objects.select_related('business').get(code=options['team'])
            result = import_history(options['manifest'], team, apply=options['apply'])
        except (Team.DoesNotExist, ValueError, OSError, TypeError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
