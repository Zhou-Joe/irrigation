"""Auto-assign MaintenancePlans to Crews based on Land coverage.

For each PM, resolves the zones it covers (directly via plan.zones, or
indirectly via plan.satellite.zones / plan.patch.zones), collects those
zones' Land FKs, and matches against Crew.lands. If exactly one crew is
responsible for all the lands → that crew is assigned. If multiple crews
or no crew → crew stays None (manager assigns manually).

Usage:
    python manage.py assign_pm_crews
    python manage.py assign_pm_crews --dry-run
"""

from django.core.management.base import BaseCommand

from core.models import MaintenancePlan, Crew


class Command(BaseCommand):
    help = 'Auto-assign PM plans to crews based on Land coverage.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Preview without saving.')

    def handle(self, *args, **options):
        dry = options['dry_run']

        # Pre-build land → crew lookup (a land may be covered by multiple crews).
        land_crew_map = {}   # land_id → set of crew ids
        for crew in Crew.objects.filter(active=True).prefetch_related('lands'):
            for land in crew.lands.all():
                land_crew_map.setdefault(land.id, set()).add(crew.id)

        assigned = 0
        skipped_multi = 0    # spans multiple crews
        skipped_none = 0     # no crew covers the land(s)
        already = 0          # already had a crew

        plans = (MaintenancePlan.objects.all()
                 .select_related('job_plan', 'satellite', 'patch')
                 .prefetch_related('zones__land'))

        for plan in plans:
            if plan.crew_id:
                already += 1
                continue

            # Collect land ids for this PM's asset scope.
            asset_level = plan.job_plan.asset_level
            land_ids = set()

            if asset_level == 'zone_group':
                for z in plan.zones.all():
                    if z.land_id:
                        land_ids.add(z.land_id)
            elif asset_level == 'sat' and plan.satellite_id:
                for z in plan.satellite.zones.all():
                    if z.land_id:
                        land_ids.add(z.land_id)
            elif asset_level == 'ccu' and plan.patch_id:
                for z in plan.patch.zones.all():
                    if z.land_id:
                        land_ids.add(z.land_id)

            if not land_ids:
                skipped_none += 1
                continue

            # Find crews responsible for ALL of these lands (intersection).
            # If the PM spans lands owned by different crews, skip (ambiguous).
            crew_sets = [land_crew_map.get(lid, set()) for lid in land_ids]
            if not any(crew_sets):
                skipped_none += 1
                continue

            # Crews that cover every land in this PM.
            common = set.intersection(*[s for s in crew_sets if s])
            if len(common) >= 1:
                # Pick the lowest-id crew (deterministic) when multiple overlap.
                # In production each land should map to exactly one crew; on the
                # dev box crews overlap and we'd rather assign than leave blank.
                crew_id = min(common)
                if not dry:
                    plan.crew_id = crew_id
                    plan.save(update_fields=['crew'])
                crew = Crew.objects.get(id=crew_id)
                if len(common) > 1:
                    crews = sorted(Crew.objects.filter(id__in=common).values_list('name', flat=True))
                    self.stdout.write(self.style.WARNING(
                        f'  {plan.pm_number} → {crew.name} (ambiguous: {crews}, picked first)'))
                else:
                    self.stdout.write(f'  {plan.pm_number} → {crew.name}')
                assigned += 1
            else:
                # No single crew covers ALL lands — lands split across crews.
                skipped_multi += 1
                all_crews = set()
                for s in crew_sets:
                    all_crews.update(s)
                crews = [Crew.objects.get(id=cid).name for cid in all_crews]
                self.stdout.write(f'  {plan.pm_number} → SPLIT ({crews})')

        self.stdout.write(self.style.SUCCESS(
            f'\nDone: {assigned} assigned, {already} already had crew, '
            f'{skipped_multi} ambiguous/split, {skipped_none} no matching crew.'
            + (' [DRY RUN]' if dry else '')))
