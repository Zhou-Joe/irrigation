"""Portable business regressions; never use the ordinary database or caches."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DJANGO_SETTINGS_MODULE']='config.settings'
os.environ['DEBUG']='True'
os.environ['SECRET_KEY']='isolated-business-regression-tests'
from django.conf import settings
settings.CACHES={key:{'BACKEND':'django.core.cache.backends.locmem.LocMemCache'} for key in ('default','dxffile')}
settings.DATABASES['default']['TEST']={'NAME':':memory:'}
import django
django.setup()
from django.test.runner import DiscoverRunner
sys.exit(bool(DiscoverRunner(verbosity=1).run_tests(sys.argv[1:] or ['core'])))
