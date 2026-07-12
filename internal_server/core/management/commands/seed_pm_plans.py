"""Seed JobPlanTemplates and MaintenancePlans from a bundled JSON fixture.

This command replaces the Excel-based ``import_pm_plans`` for environments
where the Excel file isn't available. The fixture (``core/fixtures/pm_seed.json``)
contains all 13 JobPlans and 719 MaintenancePlans exported from the dev
database, using **code-based references** (Patch.code, Satellite.code,
Zone.code) instead of PKs so it works on any database with matching
Patch/Satellite/Zone records.

Usage:
    python manage.py seed_pm_plans              # create missing records
    python manage.py seed_pm_plans --dry-run    # preview only
"""

import json
import os

from django.core.management.base import BaseCommand

from core.models import (
    JobPlanTemplate, MaintenancePlan, Patch, Satellite, Zone,
)


class Command(BaseCommand):
    help = 'Seed PM JobPlans and MaintenancePlans from bundled JSON fixture.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Preview without creating.')

    def handle(self, *args, **options):
        dry = options['dry_run']
        fixture_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'fixtures', 'pm_seed.json',
        )
        if not os.path.exists(fixture_path):
            self.stdout.write(self.style.ERROR(f'Fixture not found: {fixture_path}'))
            return

        with open(fixture_path, encoding='utf-8') as f:
            data = json.load(f)

        # Pre-build code→object maps for fast resolution.
        patch_map = {p.code: p for p in Patch.objects.all()}
        sat_map = {s.code: s for s in Satellite.objects.all()}
        zone_map = {z.code: z for z in Zone.objects.all()}

        jp_created = jp_skipped = 0
        pm_created = pm_skipped = pm_unresolved = 0

        for record in data:
            model = record['model']
            fields = record['fields']

            if model == 'core.jobplantemplate':
                name = fields['name']
                if JobPlanTemplate.objects.filter(name=name).exists():
                    jp_skipped += 1
                    continue
                if not dry:
                    JobPlanTemplate.objects.create(
                        name=name,
                        description=fields.get('description', ''),
                        asset_level=fields.get('asset_level', 'zone_group'),
                        active=fields.get('active', True),
                    )
                jp_created += 1
                self.stdout.write(f'  JobPlan: {name}')

            elif model == 'core.maintenanceplan':
                pm_number = fields['pm_number']
                if MaintenancePlan.objects.filter(pm_number=pm_number).exists():
                    pm_skipped += 1
                    continue

                # Resolve job_plan by name.
                jp = JobPlanTemplate.objects.filter(name=fields['job_plan']).first()
                if not jp:
                    pm_unresolved += 1
                    continue

                # Resolve patch / satellite / zones by code.
                patch = patch_map.get(fields['patch_code']) if fields.get('patch_code') else None
                satellite = sat_map.get(fields['satellite_code']) if fields.get('satellite_code') else None
                zone_codes = fields.get('zone_codes') or []
                zones = [zone_map[c] for c in zone_codes if c in zone_map]

                if not dry:
                    plan = MaintenancePlan.objects.create(
                        pm_number=pm_number,
                        job_plan=jp,
                        frequency_value=fields['frequency_value'],
                        frequency_unit=fields['frequency_unit'],
                        start_date=fields['start_date'],
                        lead_days=fields.get('lead_days', 1),
                        active=fields.get('active', True),
                        remark_template=fields.get('remark_template', ''),
                        patch=patch,
                        satellite=satellite,
                    )
                    if zones:
                        plan.zones.set(zones)
                pm_created += 1

        self.stdout.write(self.style.SUCCESS(
            f'\nDone: {jp_created} JobPlans created, {jp_skipped} skipped; '
            f'{pm_created} PM Plans created, {pm_skipped} skipped, {pm_unresolved} unresolved'
            + (' [DRY RUN]' if dry else '')
        ))
