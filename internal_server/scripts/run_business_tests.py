"""Portable business regressions; never use the ordinary database or caches."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DJANGO_SETTINGS_MODULE']='config.settings'
os.environ['DEBUG']='True'
os.environ['SECRET_KEY']='isolated-business-regression-tests'
from django.conf import settings
settings.CACHES={key:{'BACKEND':'django.core.cache.backends.locmem.LocMemCache'} for key in ('default','dxffile')}
settings.DATABASES['default']['TEST']={'NAME':':memory:'}
private = tempfile.TemporaryDirectory(prefix='ai-test-', dir=settings.BASE_DIR)
settings.AI_PRIVATE_ROOT = Path(private.name)
import django
django.setup()
from django.test.runner import DiscoverRunner
try:
    failed = bool(DiscoverRunner(verbosity=1).run_tests(sys.argv[1:] or ['core']))
finally:
    from core.ai_agent import _checkpoint_saver
    if _checkpoint_saver.cache_info().currsize:
        _checkpoint_saver().conn.close()
        _checkpoint_saver.cache_clear()
    private.cleanup()
sys.exit(failed)
