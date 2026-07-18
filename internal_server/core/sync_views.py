"""Read-only Maxicom sync status endpoints.

The Maxicom2 sync agent — which POSTed data to a ``/api/sync/receive`` endpoint
that upserted/appended every Maxicom table — has been retired. Maxicom data now
flows in via the nightly mdb import (``import_maxicom_mdb_linux``, run by
``maxicom_nightly.sh``), which reads XA_LOG directly. The write endpoint and all
its ``_upsert_*`` / ``_append_*`` helpers have been removed.

Only the read-only status endpoints remain: ``sync_status`` (table counts) and
``agent_status`` (last heartbeat), both consumed by the dashboard's sync
indicator. They honour either a logged-in session or an ``X-Sync-Key`` header.
"""

import os
import hmac
from django.http import JsonResponse
from django.utils import timezone
from core.models import (
    MaxicomController, MaxicomSchedule,
    MaxicomFlowZone, MaxicomWeatherStation, MaxicomWeatherLog,
    MaxicomEvent, MaxicomFlowReading, MaxicomSignalLog,
    MaxicomETCheckbook, MaxicomRuntime, SyncAgentHeartbeat,
    Patch,
)

# Retained so the status endpoints can still be read with X-Sync-Key if a key is
# configured, even though no agent posts data anymore.
SYNC_API_KEY = os.environ.get('SYNC_API_KEY', '')


def verify_api_key(request):
    """Verify the sync API key from request header using a constant-time compare."""
    if not SYNC_API_KEY:
        return False
    key = request.headers.get('X-Sync-Key', '')
    return hmac.compare_digest(key, SYNC_API_KEY)


def _auth_key_or_session(request):
    """Allow either a logged-in session (dashboard) or a valid X-Sync-Key."""
    return request.user.is_authenticated or verify_api_key(request)


def sync_status(request):
    """Return current Maxicom table counts + latest timestamps."""
    if not _auth_key_or_session(request):
        return JsonResponse({'error': 'Auth required'}, status=401)
    counts = {
        'sites': Patch.objects.count(),
        'stations': Patch.objects.filter(parent__isnull=False).count(),
        'controllers': MaxicomController.objects.count(),
        'schedules': MaxicomSchedule.objects.count(),
        'flow_zones': MaxicomFlowZone.objects.count(),
        'weather_stations': MaxicomWeatherStation.objects.count(),
        'weather_logs': MaxicomWeatherLog.objects.count(),
        'events': MaxicomEvent.objects.count(),
        'et_checkbook': MaxicomETCheckbook.objects.count(),
        'runtime': MaxicomRuntime.objects.count(),
        'signal_logs': MaxicomSignalLog.objects.count(),
        'flow_readings': MaxicomFlowReading.objects.count(),
    }
    latest = {}
    try:
        latest['event'] = MaxicomEvent.objects.order_by('-timestamp').values_list('timestamp', flat=True).first()
    except Exception:
        pass
    try:
        latest['weather'] = MaxicomWeatherLog.objects.order_by('-timestamp').values_list('timestamp', flat=True).first()
    except Exception:
        pass
    return JsonResponse({'counts': counts, 'latest': latest})


def agent_status(request):
    """Return sync agent connection status based on heartbeat (dashboard widget).

    With the sync agent retired this will report ``offline`` /
    ``never_connected``; the nightly mdb import keeps the data fresh instead.
    """
    if not _auth_key_or_session(request):
        return JsonResponse({'error': 'Auth required'}, status=401)
    try:
        heartbeat = SyncAgentHeartbeat.objects.get(pk=1)
        last = heartbeat.last_heartbeat
        if timezone.is_naive(last):
            last = timezone.make_aware(last)
        now = timezone.now()
        elapsed = (now - last).total_seconds()
        status = 'online' if elapsed < 900 else 'offline'
        return JsonResponse({
            'status': status,
            'last_heartbeat': last.isoformat(),
            'seconds_since_heartbeat': int(elapsed),
            'last_sync_counts': heartbeat.last_sync_counts,
            'agent_version': heartbeat.agent_version,
        })
    except SyncAgentHeartbeat.DoesNotExist:
        return JsonResponse({
            'status': 'never_connected',
            'last_heartbeat': None,
            'seconds_since_heartbeat': None,
            'last_sync_counts': {},
            'agent_version': '',
        })
