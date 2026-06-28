"""Generate missing thumbnails for existing workorder photos/videos.

Thumbnails (``*_thumb.jpg``) are created on upload by ``_save_photo``, but media
that existed before that change has none. This command scans every photo path in
WorkReport.photos and WorkReportEntry.photos and backfills the thumbnail next to
it. Safe to re-run — skips paths that already have a thumbnail.

Usage:
    python manage.py backfill_thumbnails
    python manage.py backfill_thumbnails --dry-run   # report what would be done
"""
import os

from django.core.management.base import BaseCommand
from django.core.files.storage import default_storage

from core.models import WorkReport, WorkReportEntry
from core.workorder_tree_views import thumb_path, _make_thumbnail


class Command(BaseCommand):
    help = 'Backfill *_thumb.jpg thumbnails for existing workorder photos/videos.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Report without writing.')

    def handle(self, *args, **opts):
        dry = opts['dry_run']
        # Collect every distinct media path referenced by report + entry photos.
        paths = set()
        for p in WorkReport.objects.exclude(photos=[]).values_list('photos', flat=True):
            if isinstance(p, list):
                paths.update(p)
        for p in WorkReportEntry.objects.exclude(photos=[]).values_list('photos', flat=True):
            if isinstance(p, list):
                paths.update(p)

        self.stdout.write(f'Found {len(paths)} distinct media paths.')

        created = 0
        skipped_existing = 0
        missing_original = 0
        errors = 0

        for i, path in enumerate(sorted(paths), 1):
            thumb = thumb_path(path)
            if default_storage.exists(thumb):
                skipped_existing += 1
                continue
            if not default_storage.exists(path):
                missing_original += 1
                continue
            if dry:
                created += 1
                continue
            try:
                # _make_thumbnail expects a seekable file object (it opens it with
                # Pillow); open the existing original from storage and pass that.
                # The video branch ignores the file object and reads the path via
                # ffmpeg, so this works for both photos and videos.
                with default_storage.open(path, 'rb') as f:
                    _make_thumbnail(path, f)
                if default_storage.exists(thumb):
                    created += 1
                else:
                    errors += 1
            except Exception as e:
                errors += 1
                self.stderr.write(f'  ERROR {path}: {e}')
            if i % 50 == 0:
                self.stdout.write(f'  ...{i}/{len(paths)} processed')

        self.stdout.write(self.style.SUCCESS(
            f'Done. created={created} skipped(existing)={skipped_existing} '
            f'missing_original={missing_original} errors={errors}'
            + (' [DRY RUN]' if dry else '')
        ))
