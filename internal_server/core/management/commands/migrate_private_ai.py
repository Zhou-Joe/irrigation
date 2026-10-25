"""Preserve existing AI history while retiring all public media paths."""
import shutil
import sqlite3
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand
from core.ai_storage import private_root, THREAD_RE


class Command(BaseCommand):
    help = 'Copy legacy AI checkpoints/workspaces into protected storage (idempotent).'

    def handle(self, *args, **options):
        private = private_root()
        old = Path(settings.MEDIA_ROOT)
        source = old / 'ai_checkpoints.sqlite3'
        target = private / 'checkpoints.sqlite3'
        if source.is_file() and not target.exists():
            with sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True) as src, sqlite3.connect(target) as dst:
                src.backup(dst)
            target.chmod(0o600)
        workspaces = old / 'ai_workspaces'
        if workspaces.is_dir():
            for path in workspaces.iterdir():
                if path.is_symlink() or not path.is_dir() or not THREAD_RE.fullmatch(path.name):
                    continue
                dst = private / 'workspaces' / path.name
                dst.mkdir(mode=0o700, parents=True, exist_ok=True)
                for item in path.iterdir():
                    if item.is_file() and not item.is_symlink() and not (dst / item.name).exists():
                        shutil.copyfile(item, dst / item.name)
        # Register existing owner-prefixed conversations so history remains
        # discoverable after the upgrade, including chats that used no tools.
        from core.models import AIConversation
        from django.contrib.auth.models import User
        identifiers=set()
        directory=private/'workspaces'
        if directory.exists():identifiers.update(p.name for p in directory.iterdir() if p.is_dir())
        if target.exists():
            with sqlite3.connect(target) as connection:
                if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='checkpoints'").fetchone():
                    identifiers.update(r[0] for r in connection.execute('SELECT DISTINCT thread_id FROM checkpoints'))
        for thread in identifiers:
            if not THREAD_RE.fullmatch(thread):continue
            owner_id=int(thread.split('-',1)[0][1:])
            if User.objects.filter(pk=owner_id).exists():
                AIConversation.objects.get_or_create(id=thread,defaults={'owner_id':owner_id,'title':'历史对话'})
        self.stdout.write('Private AI storage ready; legacy media paths remain denied.')
