"""Isolated local pilot. Run with the project's Python; never touches the real DB.

    .venv/Scripts/python.exe internal_server/scripts/run_multi_team_preview.py

Only binds loopback. Demo accounts/password are intentionally local test data.
"""
import argparse
import os
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[2]
PREVIEW = ROOT / '.tmp-pm-review' / 'multi-team-preview'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8786)
    parser.add_argument('--prepare-only', action='store_true')
    options = parser.parse_args()
    PREVIEW.mkdir(parents=True, exist_ok=True)
    socket.getfqdn = lambda name='': 'localhost'
    sys.path.insert(0, str(ROOT / 'internal_server'))
    os.environ.update(DJANGO_SETTINGS_MODULE='config.settings', DEBUG='True', MULTI_TEAM_ENABLED='True',
                      SECRET_KEY='local-only-multi-team-preview-key-not-for-production')
    from django.conf import settings
    settings.DATABASES['default']['NAME'] = PREVIEW / 'db.sqlite3'
    settings.CACHES = {key: {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'} for key in ('default','dxffile')}
    settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
    settings.ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
    settings.SESSION_COOKIE_SECURE = False
    settings.CSRF_COOKIE_SECURE = False
    settings.MEDIA_ROOT = PREVIEW / 'media'
    settings.AI_PRIVATE_ROOT = PREVIEW / 'private_ai'
    import django
    django.setup()
    from django.core.management import call_command
    from django.contrib.auth import get_user_model
    from core.models import Zone, Worker, ManagerProfile
    from operations.models import Team, Membership, Location, LocationGrant
    from operations.catalog_import import import_reference

    call_command('migrate', verbosity=0)
    call_command('bootstrap_operations', verbosity=0)
    it = Team.objects.get(code='irrigation')
    pt = Team.objects.get(code='pest-control')
    password = 'Pilot-Test!2026'
    users = {}
    for username in ('pilot-admin','irrigation-manager','pest-manager','pest-field','dual-role'):
        user, created = get_user_model().objects.get_or_create(username=username)
        if created:
            user.set_password(password)
            user.is_superuser = user.is_staff = username == 'pilot-admin'
            user.save()
        users[username] = user
    ManagerProfile.objects.get_or_create(user=users['irrigation-manager'], defaults={
        'employee_id':'PILOT-IM','full_name':'灌溉经理（测试）'})
    for username in ('pest-field','dual-role'):
        Worker.objects.get_or_create(user=users[username], defaults={'employee_id':'PILOT-'+username,'full_name':username})
    for username, team, role in [('pilot-admin',it,'manager'),('pilot-admin',pt,'manager'),
        ('irrigation-manager',it,'manager'),('pest-manager',pt,'manager'),
        ('pest-field',pt,'field'),('dual-role',it,'field'),('dual-role',pt,'manager')]:
        Membership.objects.get_or_create(user=users[username], team=team, defaults={'role':role})
    for code, name, shift in [('6-7-28','共享绿地（本地示例）',0),('6-7-29','灌溉专用区（本地示例）',.001)]:
        ring = [{'lat':31.1488+shift,'lng':121.6540}, {'lat':31.1491+shift,'lng':121.6544},
                {'lat':31.1487+shift,'lng':121.6547}, {'lat':31.1488+shift,'lng':121.6540}]
        zone, _ = Zone.objects.get_or_create(code=code, defaults={'name':name,'boundary_points':[ring]})
        location, created = Location.objects.get_or_create(legacy_zone=zone, defaults={
            'owner_team':it,'code':code,'name':name})
        if code == '6-7-28' and created:
            LocationGrant.objects.get_or_create(location=location,team=pt)
    building, _ = Location.objects.get_or_create(owner_team=pt, code='BLDG-A', defaults={
        'name':'行政楼 A（本地示例）','kind':'building','latitude':'31.1489000','longitude':'121.6551000'})
    Location.objects.get_or_create(owner_team=pt, code='PANTRY', defaults={
        'name':'二层茶水间','kind':'room','parent':building,'description':'室内地点可不设置地图边界或定位点。'})
    Location.objects.get_or_create(owner_team=pt, code='TRAP-017', defaults={
        'name':'外围监测点 017','kind':'monitoring','latitude':'31.1484000','longitude':'121.6546000'})
    catalog, _ = import_reference(ROOT / 'PM管理_层级结构整理版.md', pt.business)
    print(f'LOCAL PILOT: http://127.0.0.1:{options.port}/', flush=True)
    print('Demo accounts: ' + ', '.join(users), flush=True)
    print('Local demo password: ' + password, flush=True)
    print(f'Reference nodes: {catalog.nodes.count()}; isolated DB: {PREVIEW / "db.sqlite3"}', flush=True)
    if options.prepare_only:
        return
    from socketserver import ThreadingMixIn
    from wsgiref.simple_server import make_server, WSGIServer
    from django.core.wsgi import get_wsgi_application
    from django.contrib.staticfiles.handlers import StaticFilesHandler

    class ThreadedServer(ThreadingMixIn, WSGIServer):
        daemon_threads = True
    with make_server('127.0.0.1', options.port, StaticFilesHandler(get_wsgi_application()), server_class=ThreadedServer) as server:
        server.serve_forever()


if __name__ == '__main__':
    main()
