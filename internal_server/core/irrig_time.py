"""Maxicom runtime timestamps are UTC; application inputs and labels are local.

Django cannot apply USE_TZ to a CharField. Local query windows therefore convert
explicitly. Production reconciliation covers CCU2 (2026-08-27), CCU7 (2026-09-02)
and CCU44 (2026-08-18): all 20 operator-provided Actual Log values match.
"""
from datetime import datetime, time, timedelta, timezone as datetime_timezone

from django.utils import timezone


def _compact_datetime(value, *, end=False):
    value = str(value).strip()
    if len(value) not in (8, 10, 12, 14) or not value.isdigit():
        raise ValueError('Invalid compact Maxicom timestamp')
    suffix = '235959' if end else '000000'
    return datetime.strptime(value + suffix[len(value) - 8:], '%Y%m%d%H%M%S')


def local_timestamp_to_utc(value, *, end=False):
    """Convert a local date/hour/minute/second input to an exact UTC bound."""
    if not value:
        return ''
    local = _compact_datetime(value, end=end).replace(tzinfo=timezone.get_default_timezone())
    return local.astimezone(datetime_timezone.utc).strftime('%Y%m%d%H%M%S')


def runtime_window_bounds(local_from, local_to):
    start = local_timestamp_to_utc(local_from)
    end = local_timestamp_to_utc(local_to, end=True)
    if start and end and start > end:
        raise ValueError('The end of the runtime window precedes its start')
    return start, end


def utc_timestamp_to_local(value):
    """Return a compact local timestamp for a raw MDB/runtime UTC timestamp."""
    if not value:
        return ''
    utc = _compact_datetime(value).replace(tzinfo=datetime_timezone.utc)
    return utc.astimezone(timezone.get_default_timezone()).strftime('%Y%m%d%H%M%S')


def irrigation_day_for_utc(value):
    """Local irrigation-day date for a UTC reading; 22:00 rolls forward."""
    local = _compact_datetime(utc_timestamp_to_local(value))
    return local.date() + timedelta(days=local.time() >= time(22))


def irrigation_day_bounds(start, end):
    """Local UI/export bounds for irrigation days start..end, to the minute."""
    f = (start - timedelta(days=1)).strftime('%Y%m%d') + '2200'
    t = end.strftime('%Y%m%d') + '2159'
    return f, t


def irrigation_day_utc_bounds(start, end):
    """Database query bounds for local irrigation days start..end."""
    return runtime_window_bounds(*irrigation_day_bounds(start, end))


def complete_irrigation_days(local_from, local_to):
    """Covered local day labels, or None when daily meter totals lack precision."""
    if not local_from or not local_to:
        return None
    start = _compact_datetime(local_from)
    end = _compact_datetime(local_to, end=True)
    if start.time() != time(22) or end.time() != time(21, 59, 59):
        return None
    first = start.date() + timedelta(days=1)
    return (first, end.date()) if first <= end.date() else None
