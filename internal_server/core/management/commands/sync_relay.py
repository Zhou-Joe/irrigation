"""
Management command to poll cloud relay and import work logs.

Polls the Cloudflare Worker at /api/pending-uploads?last_sync=<timestamp>
and imports pending work log entries into the local database.
"""

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import WorkLog, Worker, Zone


class Command(BaseCommand):
    """
    Poll cloud relay and import pending work logs.

    Fetches pending uploads from the cloud relay and imports them
    into the local database. Uses relay_id to prevent duplicate imports.
    """

    help = "Poll cloud relay and import pending work logs"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be imported without actually importing",
        )
        parser.add_argument(
            "--force-sync",
            action="store_true",
            help="Force sync from beginning (ignores last_sync timestamp)",
        )

    def get_last_sync_timestamp(self):
        """Get the last sync timestamp from the most recent WorkLog."""
        last_log = WorkLog.objects.order_by("-work_timestamp").first()
        if last_log:
            return last_log.work_timestamp
        # Return a very old date if no logs exist
        return timezone.datetime(2000, 1, 1, tzinfo=timezone.utc)

    def fetch_pending_uploads(self, last_sync):
        """Fetch pending uploads from cloud relay."""
        url = f"{settings.CLOUD_RELAY_BASE_URL}/api/pending-uploads"
        params = {"last_sync": last_sync.isoformat()}

        headers = {}
        if settings.CLOUD_RELAY_POLL_TOKEN:
            headers["Authorization"] = f"Bearer {settings.CLOUD_RELAY_POLL_TOKEN}"

        try:
            response = requests.get(url, params=params, headers=headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            self.stderr.write(self.style.ERROR(f"Failed to fetch from cloud relay: {e}"))
            return None

    def get_or_create_worker(self, employee_id, full_name=None, phone=None):
        """Get or create a worker by employee_id."""
        worker, created = Worker.objects.get_or_create(
            employee_id=employee_id,
            defaults={
                "full_name": full_name or f"Worker {employee_id}",
                "phone": phone or "",
            }
        )
        return worker, created

    def get_zone_by_code(self, code):
        """Get a zone by its code."""
        try:
            zone = Zone.objects.get(code=code)
            return zone, False
        except Zone.DoesNotExist:
            self.stderr.write(self.style.WARNING(f"Zone with code '{code}' not found"))
            return None, False

    def import_work_log(self, record, dry_run=False):
        """
        Import a single work log record.

        Returns:
            tuple: (success: bool, skipped: bool, message: str)
        """
        relay_id = record.get("relay_id")

        if not relay_id:
            return False, True, "Missing relay_id"

        # Check for duplicate
        if WorkLog.objects.filter(relay_id=relay_id).exists():
            return False, True, f"Duplicate relay_id: {relay_id}"

        # Get or create worker
        employee_id = record.get("employee_id")
        if not employee_id:
            return False, True, "Missing employee_id"

        worker, worker_created = self.get_or_create_worker(
            employee_id=employee_id,
            full_name=record.get("worker_name"),
            phone=record.get("worker_phone"),
        )
        if worker_created:
            self.stdout.write(f"  Created worker: {worker}")

        # Get zone by code
        zone_code = record.get("zone_code")
        if not zone_code:
            return False, True, "Missing zone_code"

        zone, _ = self.get_zone_by_code(zone_code)
        if not zone:
            return False, True, f"Zone '{zone_code}' not found"

        # Get or create work order (optional)
        work_order = None
        work_order_id = record.get("work_order_id")
        if work_order_id:
            from core.models import WorkOrder

            work_order = WorkOrder.objects.filter(id=work_order_id).first()

        # Create work log
        if not dry_run:
            try:
                WorkLog.objects.create(
                    zone=zone,
                    worker=worker,
                    work_order=work_order,
                    work_type=record.get("work_type", "general"),
                    notes=record.get("notes", ""),
                    latitude=record.get("latitude"),
                    longitude=record.get("longitude"),
                    work_timestamp=record.get(
                        "work_timestamp", timezone.now().isoformat()
                    ),
                    relay_id=relay_id,
                )
                return True, False, f"Imported: {relay_id}"
            except Exception as e:
                return False, True, f"Error creating WorkLog: {e}"
        else:
            return True, False, f"Would import: {relay_id}"

    @transaction.atomic
    def handle(self, *args, **options):
        """Main command handler."""
        dry_run = options["dry_run"]
        force_sync = options["force_sync"]

        self.stdout.write(self.style.SUCCESS("Starting cloud relay sync..."))

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No changes will be made"))

        # Get last sync timestamp
        if force_sync:
            self.stdout.write(
                self.style.WARNING("Force sync - fetching all records from beginning")
            )
            last_sync = timezone.datetime(2000, 1, 1, tzinfo=timezone.utc)
        else:
            last_sync = self.get_last_sync_timestamp()
            self.stdout.write(f"Last sync timestamp: {last_sync}")

        # Fetch pending uploads
        self.stdout.write(f"Fetching pending uploads from {settings.CLOUD_RELAY_BASE_URL}")
        data = self.fetch_pending_uploads(last_sync)

        if data is None:
            self.stderr.write(self.style.ERROR("Aborting due to fetch failure"))
            return

        records = data.get("records", [])
        total_records = len(records)

        self.stdout.write(f"Found {total_records} pending records")

        if total_records == 0:
            self.stdout.write(self.style.SUCCESS("No new records to import"))
            return

        # Process records
        imported_count = 0
        skipped_count = 0
        error_count = 0

        for i, record in enumerate(records, 1):
            self.stdout.write(f"[{i}/{total_records}] Processing record...")
            success, skipped, message = self.import_work_log(record, dry_run=dry_run)

            if success:
                imported_count += 1
                self.stdout.write(self.style.SUCCESS(f"  {message}"))
            elif skipped:
                skipped_count += 1
                self.stdout.write(self.style.WARNING(f"  Skipped: {message}"))
            else:
                error_count += 1
                self.stderr.write(self.style.ERROR(f"  Error: {message}"))

        # Print summary
        self.stdout.write("\n" + "=" * 50)
        self.stdout.write(self.style.SUCCESS("Sync completed!"))
        self.stdout.write(f"  Total records: {total_records}")
        self.stdout.write(f"  Imported: {imported_count}")
        self.stdout.write(self.style.WARNING(f"  Skipped: {skipped_count}"))
        if error_count > 0:
            self.stderr.write(self.style.ERROR(f"  Errors: {error_count}"))

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "\nDRY RUN complete - no actual changes were made"
                )
            )
