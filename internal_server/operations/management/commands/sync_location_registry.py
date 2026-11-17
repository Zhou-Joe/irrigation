from django.core.management.base import BaseCommand

from operations.registry import sync_irrigation_locations


class Command(BaseCommand):
    help='Register irrigation zones as places without sharing them with any other team.'

    def handle(self,*args,**options):
        result=sync_irrigation_locations()
        self.stdout.write(self.style.SUCCESS(
            f'Location registry: {result["created"]} added, {result["updated"]} metadata updated; no team visibility grants changed.'))
