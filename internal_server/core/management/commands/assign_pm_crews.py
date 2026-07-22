"""Auto-assign MaintenancePlans to Crews based on asset coverage.

Matching priority per plan:
  1. CCU/SAT-level PMs are first matched by CCU (Crew.patches). A CCU-level
     PM maps to its plan.patch; a SAT-level PM maps to its satellite.patch.
     If a crew is responsible for that CCU → assign it.
  2. Otherwise (zone_group PMs, or no CCU match) fall back to Land coverage:
     collect the zones' Land FKs and intersect Crew.lands. If one crew covers
     all lands → assign it.

If neither resolves, crew stays None (manager assigns manually).

Usage:
    python manage.py assign_pm_crews
    python manage.py assign_pm_crews --dry-run
"""

from django.core.management.base import BaseCommand

from core.models import MaintenancePlan, Crew


class Command(BaseCommand):
    help = 'Auto-assign PM plans to crews (CCU-first, then Land coverage).'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Preview without saving.')

    def handle(self, *args, **options):
        dry = options['dry_run']

        # Pre-build land → crew lookup (a land may be covered by multiple crews).
        land_crew_map = {}   # land_id → set of crew ids
        # Pre-build ccu(patch) → crew lookup (a CCU may be covered by multiple crews).
        patch_crew_map = {}  # patch_id → set of crew ids
        for crew in (Crew.objects.filter(active=True)
                     .prefetch_related('lands', 'patches')):
            for land in crew.lands.all():
                land_crew_map.setdefault(land.id, set()).add(crew.id)
            for patch in crew.patches.all():
                patch_crew_map.setdefault(patch.id, set()).add(crew.id)

        assigned_ccu = 0     # assigned via CCU match
        assigned_land = 0    # assigned via Land match
        skipped_multi = 0    # spans multiple crews (land fallback)
        skipped_none = 0     # no crew covers the asset
        already = 0          # already had a crew

        plans = (MaintenancePlan.objects.all()
                 .select_related('job_plan', 'satellite', 'satellite__patch', 'patch')
                 .prefetch_related('zones__land'))

        for plan in plans:
            if plan.crew_id:
                already += 1
                continue

            asset_level = plan.job_plan.asset_level

            # ── Step 1: CCU match (CCU/SAT-level PMs only) ──────────────
            ccu_patch = None
            if asset_level == 'ccu' and plan.patch_id:
                ccu_patch = plan.patch
            elif asset_level == 'sat' and plan.satellite_id:
                ccu_patch = plan.satellite.patch  # may be None

            if ccu_patch and ccu_patch.id in patch_crew_map:
                common = patch_crew_map[ccu_patch.id]
                crew_id = min(common)  # deterministic pick when ambiguous
                if not dry:
                    plan.crew_id = crew_id
                    plan.save(update_fields=['crew'])
                crew = Crew.objects.get(id=crew_id)
                if len(common) > 1:
                    crews = sorted(Crew.objects.filter(id__in=common).values_list('name', flat=True))
                    self.stdout.write(self.style.WARNING(
                        f'  {plan.pm_number} → {crew.name} '
                        f'(by-CCU {ccu_patch.code}; ambiguous: {crews}, picked first)'))
                else:
                    self.stdout.write(f'  {plan.pm_number} → {crew.name} (by-CCU {ccu_patch.code})')
                assigned_ccu += 1
                continue

            # ── Step 2: Land fallback (zone_group, or CCU/SAT w/o CCU crew) ─
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
                        f'  {plan.pm_number} → {crew.name} (by-Land; ambiguous: {crews}, picked first)'))
                else:
                    self.stdout.write(f'  {plan.pm_number} → {crew.name} (by-Land)')
                assigned_land += 1
            else:
                # No single crew covers ALL lands — lands split across crews.
                skipped_multi += 1
                all_crews = set()
                for s in crew_sets:
                    all_crews.update(s)
                crews = [Crew.objects.get(id=cid).name for cid in all_crews]
                self.stdout.write(f'  {plan.pm_number} → SPLIT ({crews})')

        self.stdout.write(self.style.SUCCESS(
            f'\nDone: {assigned_ccu + assigned_land} assigned '
            f'({assigned_ccu} by-CCU, {assigned_land} by-Land), '
            f'{already} already had crew, '
            f'{skipped_multi} ambiguous/split, {skipped_none} no matching crew.'
            + (' [DRY RUN]' if dry else '')))
