"""Explicit, idempotent compatibility setup; never promotes existing users globally."""
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from operations.models import BusinessArea, Team, Membership


class Command(BaseCommand):
    help = 'Create irrigation/pest workspaces; optionally map existing legacy roles to irrigation memberships.'

    def add_arguments(self, parser):
        parser.add_argument('--assign-legacy', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        irrigation, _ = BusinessArea.objects.get_or_create(code='irrigation', defaults={'name': '灌溉养护'})
        pest, _ = BusinessArea.objects.get_or_create(code='pest-control', defaults={'name': '植保与虫害防治'})
        team, _ = Team.objects.get_or_create(code='irrigation', defaults={
            'business': irrigation, 'name': '灌溉团队', 'legacy_irrigation_access': True})
        Team.objects.get_or_create(code='pest-control', defaults={'business': pest, 'name': '植保团队'})
        count = 0
        if options['assign_legacy']:
            from django.contrib.auth import get_user_model
            from core.role_utils import get_user_role
            roles = {'super_admin': 'manager', 'manager': 'manager', 'field_worker': 'field', 'dept_user': 'requester'}
            for user in get_user_model().objects.filter(is_active=True):
                if Membership.objects.filter(user=user).exists():
                    continue
                role = roles.get(get_user_role(user))
                if role:
                    _, created = Membership.objects.get_or_create(user=user, team=team, defaults={'role': role})
                    count += created
        self.stdout.write(self.style.SUCCESS(f'Workspaces ready; {count} legacy memberships added. Existing memberships unchanged.'))
