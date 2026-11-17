from django.core.management.base import BaseCommand, CommandError
from operations.models import BusinessArea
from operations.catalog_import import import_reference


class Command(BaseCommand):
    help = 'Import the supplied pest outline as an immutable, non-executable reference catalogue.'

    def add_arguments(self, parser):
        parser.add_argument('path')

    def handle(self, *args, **options):
        try:
            business = BusinessArea.objects.get(code='pest-control')
            catalog, created = import_reference(options['path'], business)
        except (BusinessArea.DoesNotExist, ValueError, OSError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f'Reference {"imported" if created else "already exists"}: {catalog.nodes.count()} nodes; no tasks or schedules created.')
