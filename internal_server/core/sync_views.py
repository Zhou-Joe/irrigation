"""Django sync API endpoint for receiving data from Maxicom2 sync agent."""

import os
import json
from datetime import datetime, timedelta
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone
from core.models import (
    MaxicomSite, MaxicomController, MaxicomStation, MaxicomSchedule,
    MaxicomFlowZone, MaxicomWeatherStation, MaxicomWeatherLog,
    MaxicomEvent, MaxicomFlowReading, MaxicomSignalLog,
    MaxicomETCheckbook, MaxicomRuntime, SyncAgentHeartbeat,
)

SYNC_API_KEY = os.environ.get('SYNC_API_KEY', 'dev-sync-key-change-in-production')


def verify_api_key(request):
    """Verify the sync API key from request header."""
    key = request.headers.get('X-Sync-Key', '')
    return key == SYNC_API_KEY


@csrf_exempt
@require_POST
def sync_receive(request):
    """Receive synced data from the Maxicom2 sync agent."""
    if not verify_api_key(request):
        return JsonResponse({'error': 'Invalid API key'}, status=403)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    results = {}
    config = data.get('config', {})
    time_series = data.get('time_series', {})

    # --- Config tables: upsert ---
    results['sites'] = _upsert_sites(config.get('sites', []))
    results['controllers'] = _upsert_controllers(config.get('controllers', []))
    results['stations'] = _upsert_stations(config.get('stations', []))
    results['schedules'] = _upsert_schedules(config.get('schedules', []))
    results['flow_zones'] = _upsert_flow_zones(config.get('flow_zones', []))
    results['weather_stations'] = _upsert_weather_stations(config.get('weather_stations', []))

    # --- Time-series tables: append with dedup ---
    results['weather_logs'] = _append_weather_logs(time_series.get('weather_logs', []))
    results['events'] = _append_events(time_series.get('events', []))
    results['et_checkbook'] = _append_et_checkbook(time_series.get('et_checkbook', []))
    results['runtime'] = _append_runtime(time_series.get('runtime', []))
    results['signal_logs'] = _append_signal_logs(time_series.get('signal_logs', []))
    results['flow_readings'] = _append_flow_readings(time_series.get('flow_readings', []))

    # Update sync agent heartbeat
    heartbeat = SyncAgentHeartbeat.get_instance()
    heartbeat.last_sync_counts = results
    heartbeat.agent_version = data.get('agent_version', '')
    heartbeat.save()

    return JsonResponse({
        'status': 'ok',
        'sync_timestamp': data.get('sync_timestamp', ''),
        'results': results,
    })


@csrf_exempt
def sync_status(request):
    """Return current sync status — last record counts per table."""
    counts = {
        'sites': MaxicomSite.objects.count(),
        'controllers': MaxicomController.objects.count(),
        'stations': MaxicomStation.objects.count(),
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
    # Get latest timestamps
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
    """Return sync agent connection status based on heartbeat."""
    try:
        heartbeat = SyncAgentHeartbeat.objects.get(pk=1)
        last = heartbeat.last_heartbeat
        if timezone.is_naive(last):
            last = timezone.make_aware(last)

        now = timezone.now()
        elapsed = (now - last).total_seconds()

        # Agent syncs every 5 min; consider offline if no heartbeat for 15 min
        if elapsed < 900:  # 15 minutes
            status = 'online'
        else:
            status = 'offline'

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


# ─── Config Upsert Functions ──────────────────────────────────────────

def _upsert_sites(records):
    created, updated, errors = 0, 0, 0
    for r in records:
        try:
            idx = r.get('IndexNumber')
            if idx is None:
                continue
            defaults = {
                'name': (r.get('IndexName') or '').strip(),
                'site_number': r.get('SiteNumber', 0) or 0,
                'time_zone': r.get('SiteTimeZone', 'China') or 'China',
                'water_pricing': r.get('SiteWaterPricing'),
                'ccu_version': r.get('SiteCCUVersion', '') or '',
                'et_current': r.get('SiteWaterETCurrent'),
                'et_default': r.get('SiteWaterETDefault'),
                'et_minimum': r.get('SiteWaterETMinimum'),
                'et_maximum': r.get('SiteWaterETMaximum'),
                'crop_coefficient': r.get('SiteWaterCropCoefficient'),
                'rain_shutdown': (r.get('SiteRainShutDownApplies') == 'Y'),
                'telephone': r.get('SiteContactTelephone', '') or '',
                'date_open': r.get('DateOpen', '') or '',
                'date_close': r.get('DateClose', '') or '',
            }
            _, created_flag = MaxicomSite.objects.update_or_create(
                mdb_index=idx, defaults=defaults
            )
            if created_flag:
                created += 1
            else:
                updated += 1
        except Exception:
            errors += 1
    return {'created': created, 'updated': updated, 'errors': errors}


def _upsert_controllers(records):
    created, updated, errors = 0, 0, 0
    for r in records:
        try:
            idx = r.get('IndexNumber')
            site_idx = r.get('ControllerSiteNumber')
            site = MaxicomSite.objects.filter(mdb_index=site_idx).first()
            if not site or idx is None:
                continue
            defaults = {
                'site': site,
                'name': (r.get('IndexName') or '').strip(),
                'controller_type': '',
                'site_number': r.get('ControllerSiteNumber', 0) or 0,
                'link_number': r.get('ControllerLinkNumber', 0) or 0,
                'link_channel': r.get('ControllerLinkChannel', 0) or 0,
                'enabled': (r.get('ControllerEnabled') == 'Y'),
                'date_open': r.get('DateOpen', '') or '',
            }
            _, c = MaxicomController.objects.update_or_create(mdb_index=idx, defaults=defaults)
            if c:
                created += 1
            else:
                updated += 1
        except Exception:
            errors += 1
    return {'created': created, 'updated': updated, 'errors': errors}


def _upsert_stations(records):
    created, updated, errors = 0, 0, 0
    for r in records:
        try:
            idx = r.get('IndexNumber')
            site_idx = r.get('StationSiteNumber')
            ctrl_idx = r.get('StationControllerNumber')
            site = MaxicomSite.objects.filter(mdb_index=site_idx).first()
            if not site or idx is None:
                continue
            ctrl = MaxicomController.objects.filter(mdb_index=ctrl_idx).first()
            defaults = {
                'site': site,
                'controller': ctrl,
                'name': (r.get('IndexName') or '').strip(),
                'controller_channel': r.get('StationControllerChannel', 0) or 0,
                'precip_rate': r.get('StationPrecipFactor'),
                'flow_rate': r.get('StationFlowFactor'),
                'microclimate_factor': r.get('StationMicroclimeFactor'),
                'cycle_time': r.get('StationCycleTime'),
                'soak_time': r.get('StationSoakTime'),
                'memo': r.get('StationMemo', '') or '',
                'lockout': bool(r.get('Lockout', 0)),
                'flow_manager_priority': r.get('FloManagerPriorityLevel'),
                'date_open': r.get('DateOpen', '') or '',
            }
            _, c = MaxicomStation.objects.update_or_create(mdb_index=idx, defaults=defaults)
            if c:
                created += 1
            else:
                updated += 1
        except Exception:
            errors += 1
    return {'created': created, 'updated': updated, 'errors': errors}


def _upsert_schedules(records):
    created, updated, errors = 0, 0, 0
    for r in records:
        try:
            idx = r.get('IndexNumber')
            site_idx = r.get('ScheduleSiteNumber')
            site = MaxicomSite.objects.filter(mdb_index=site_idx).first()
            if not site or idx is None:
                continue
            defaults = {
                'site': site,
                'name': (r.get('IndexName') or '').strip(),
                'nominal_et': r.get('ScheduleNominalET'),
                'water_budget_factor': r.get('ScheduleWaterBudgetFactor'),
                'flo_manage': (r.get('ScheduleFloManage') == 'Y'),
                'send_automatic': (r.get('ScheduleSendAutomatic') == 'Y'),
                'send_protected': (r.get('ScheduleSendProtected') == 'Y'),
                'instruction_file': r.get('ScheduleInstructionFile', '') or '',
                'sensitized_et': (r.get('ScheduleSensitizedET') == 'Y'),
                'date_open': r.get('DateOpen', '') or '',
            }
            _, c = MaxicomSchedule.objects.update_or_create(mdb_index=idx, defaults=defaults)
            if c:
                created += 1
            else:
                updated += 1
        except Exception:
            errors += 1
    return {'created': created, 'updated': updated, 'errors': errors}


def _upsert_flow_zones(records):
    created, updated, errors = 0, 0, 0
    for r in records:
        try:
            idx = r.get('IndexNumber')
            site_idx = r.get('FlowZoneSiteNumber')
            site = MaxicomSite.objects.filter(mdb_index=site_idx).first()
            if not site or idx is None:
                continue
            defaults = {
                'site': site,
                'name': (r.get('IndexName') or '').strip(),
                'join_site': (r.get('FlowZoneJoinSite') == 'Y'),
            }
            _, c = MaxicomFlowZone.objects.update_or_create(mdb_index=idx, defaults=defaults)
            if c:
                created += 1
            else:
                updated += 1
        except Exception:
            errors += 1
    return {'created': created, 'updated': updated, 'errors': errors}


def _upsert_weather_stations(records):
    created, updated, errors = 0, 0, 0
    for r in records:
        try:
            idx = r.get('IndexNumber')
            if idx is None:
                continue
            defaults = {
                'name': (r.get('IndexName') or '').strip(),
                'default_et': r.get('WeatherDefaultET'),
                'time_zone': r.get('WeatherTimeZone', 'China') or 'China',
            }
            _, c = MaxicomWeatherStation.objects.update_or_create(mdb_index=idx, defaults=defaults)
            if c:
                created += 1
            else:
                updated += 1
        except Exception:
            errors += 1
    return {'created': created, 'updated': updated, 'errors': errors}


# ─── Time-Series Append Functions ─────────────────────────────────────

def _append_weather_logs(records):
    inserted, skipped = 0, 0
    for r in records:
        try:
            ws_idx = r.get('XactIndex')
            ws = MaxicomWeatherStation.objects.filter(mdb_index=ws_idx).first()
            if not ws:
                skipped += 1
                continue
            _, c = MaxicomWeatherLog.objects.get_or_create(
                weather_station=ws,
                timestamp=r.get('XactStamp', '') or '',
                defaults={
                    'temperature': r.get('Temperature'),
                    'max_temp': r.get('MaxTemp'),
                    'min_temp': r.get('MinTemp'),
                    'solar_radiation': r.get('SolarRadiation'),
                    'rainfall': r.get('RainFall'),
                    'humidity': r.get('Humidity'),
                    'wind_run': r.get('WindRun'),
                    'et': r.get('ET'),
                }
            )
            if c:
                inserted += 1
            else:
                skipped += 1
        except Exception:
            skipped += 1
    return {'inserted': inserted, 'skipped': skipped}


def _append_events(records):
    inserted, skipped = 0, 0
    for r in records:
        try:
            _, c = MaxicomEvent.objects.get_or_create(
                timestamp=r.get('XactStamp', '') or '',
                source=r.get('EventSource', '') or '',
                index=r.get('XactIndex'),
                defaults={
                    'event_number': r.get('EventNumber'),
                    'flag': r.get('EventFlag', '') or '',
                    'text': r.get('EventTextQualifier', '') or '',
                }
            )
            if c:
                inserted += 1
            else:
                skipped += 1
        except Exception:
            skipped += 1
    return {'inserted': inserted, 'skipped': skipped}


def _append_et_checkbook(records):
    inserted, skipped = 0, 0
    for r in records:
        try:
            site = MaxicomSite.objects.filter(mdb_index=r.get('SiteID')).first()
            if not site:
                skipped += 1
                continue
            _, c = MaxicomETCheckbook.objects.get_or_create(
                timestamp=r.get('XactStamp', '') or '',
                site=site,
                defaults={
                    'soil_moisture': r.get('SoilMoisture'),
                    'rainfall': r.get('Rainfall'),
                    'et': r.get('ET'),
                    'irrigation': r.get('Irrigation'),
                    'soil_moisture_capacity': r.get('SoilMoistureHoldingCapacity'),
                    'soil_refill_pct': r.get('SoilRefillPercentage'),
                }
            )
            if c:
                inserted += 1
            else:
                skipped += 1
        except Exception:
            skipped += 1
    return {'inserted': inserted, 'skipped': skipped}


def _append_runtime(records):
    inserted, skipped = 0, 0
    for r in records:
        try:
            site = MaxicomSite.objects.filter(mdb_index=r.get('SiteID')).first()
            if not site:
                skipped += 1
                continue
            stn = MaxicomStation.objects.filter(mdb_index=r.get('StationID')).first()
            _, c = MaxicomRuntime.objects.get_or_create(
                timestamp=r.get('TimeStamps', '') or '',
                site=site,
                station_id_raw=r.get('StationID', 0) or 0,
                defaults={
                    'station': stn,
                    'run_time': r.get('RunTime'),
                }
            )
            if c:
                inserted += 1
            else:
                skipped += 1
        except Exception:
            skipped += 1
    return {'inserted': inserted, 'skipped': skipped}


def _append_signal_logs(records):
    inserted, skipped = 0, 0
    for r in records:
        try:
            _, c = MaxicomSignalLog.objects.get_or_create(
                timestamp=r.get('XactStamp', '') or '',
                index=r.get('XactIndex'),
                controller_channel=r.get('ControllerChannel'),
                defaults={
                    'signal_index': r.get('SignalIndex'),
                    'signal_table': r.get('SignalTable', '') or '',
                    'signal_type': r.get('SignalType', '') or '',
                    'signal_value': r.get('SignalValue'),
                    'signal_multiplier': r.get('SignalMultiplier'),
                }
            )
            if c:
                inserted += 1
            else:
                skipped += 1
        except Exception:
            skipped += 1
    return {'inserted': inserted, 'skipped': skipped}


def _append_flow_readings(records):
    inserted, skipped = 0, 0
    for r in records:
        try:
            fz_idx = r.get('XactIndex')
            fz = MaxicomFlowZone.objects.filter(mdb_index=fz_idx).first()
            if not fz:
                skipped += 1
                continue
            _, c = MaxicomFlowReading.objects.get_or_create(
                flow_zone=fz,
                timestamp=r.get('XactStamp', '') or '',
                defaults={
                    'value': r.get('FlowZoneValue'),
                    'multiplier': r.get('FlowZoneMultiplier'),
                    'site_id': r.get('SiteID'),
                }
            )
            if c:
                inserted += 1
            else:
                skipped += 1
        except Exception:
            skipped += 1
    return {'inserted': inserted, 'skipped': skipped}