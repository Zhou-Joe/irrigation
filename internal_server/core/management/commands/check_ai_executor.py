"""Run a synthetic end-to-end calculation without business inputs or model calls."""
import tempfile
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from core.ai_executor import execute

SMOKE = r'''
import os, pathlib, socket
assert os.getuid() == 65534, 'Executor must use the unprivileged account'
assert not pathlib.Path('/var/run/docker.sock').exists()
assert not pathlib.Path('/app/.env.production').exists()
try:
    pathlib.Path('/root/should-not-write').write_text('fixture')
    raise AssertionError('Root filesystem unexpectedly writable')
except (PermissionError, OSError):
    pass
assert set(socket.if_nameindex()) == {(1, 'lo')}, 'External network is available'
cgroup = pathlib.Path('/sys/fs/cgroup')
assert int((cgroup/'memory.max').read_text()) <= 536870912, 'Memory limit is not enforced'
quota, period = (cgroup/'cpu.max').read_text().split()
assert int(quota) / int(period) <= 1, 'CPU limit is not enforced'
assert int((cgroup/'pids.max').read_text()) <= 64, 'Process limit is not enforced'
work = os.statvfs('/work')
assert work.f_blocks * work.f_frsize <= 134217728, 'Work disk limit is not enforced'
import pandas as pd
data = pd.read_csv('fixture.csv')
assert data['value'].sum() == 3
data.to_excel('executor-check.xlsx', index=False)
import matplotlib.pyplot as plt
from matplotlib import font_manager, ft2font
font = ft2font.FT2Font(font_manager.findfont('Noto Sans CJK JP', fallback_to_default=False))
assert all(ord(char) in font.get_charmap() for char in '\u704c\u6e89\u6570\u636e'), 'Chinese chart glyphs unavailable'
plt.bar(['\u6d4b\u8bd5'], [3])
plt.title('\u704c\u6e89\u6570\u636e')
plt.savefig('executor-check.png')
print('isolated-executor-ok')
'''


class Command(BaseCommand):
    help = 'Verify configured AI container with synthetic inputs only.'

    def handle(self, *args, **options):
        with tempfile.TemporaryDirectory(prefix='ai-check-', dir=settings.BASE_DIR) as temp:
            root=Path(temp)
            (root/'fixture.csv').write_text('value\n1\n2\n',encoding='utf-8')
            result=execute(SMOKE,root)
            if (result.get('error') or result.get('exit_code') != 0
                    or 'isolated-executor-ok' not in result.get('stdout','')
                    or not (root/'executor-check.xlsx').is_file()
                    or not (root/'executor-check.png').is_file()):
                raise CommandError('Executor smoke check failed: '+str(result.get('error') or result.get('stderr') or 'missing output'))
        self.stdout.write(self.style.SUCCESS('Isolated AI executor verified with synthetic data.'))
