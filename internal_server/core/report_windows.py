"""Local scheduled-report windows, including legacy hour-inclusive settings."""
from datetime import timedelta


def irrigation_email_window(window, now):
    """Return exact local compact bounds without changing saved legacy windows.

    Old hour-only settings included the entire ending hour. New settings store
    minutes/seconds explicitly and default to yesterday 08:00 -> today 08:00.
    """
    window = window or {}
    legacy = bool(window) and not any(
        key in window for key in ('minute_start', 'minute_end', 'second_start', 'second_end'))
    defaults = {'days_start': 1, 'days_end': 0,
                'hour_start': 0 if legacy else 8, 'hour_end': 23 if legacy else 8,
                'minute_start': 0, 'minute_end': 59 if legacy else 0,
                'second_start': 0, 'second_end': 59 if legacy else 0}
    values = {key: int(window.get(key, default)) for key, default in defaults.items()}
    for suffix in ('start', 'end'):
        if not 0 <= values['days_' + suffix] <= 36500:
            raise ValueError('报表天数必须在 0–36500 之间')
        for field, maximum in (('hour', 23), ('minute', 59), ('second', 59)):
            if not 0 <= values[field + '_' + suffix] <= maximum:
                raise ValueError('报表时间无效')
    def bound(suffix):
        return (now - timedelta(days=values['days_' + suffix])).replace(
            hour=values['hour_' + suffix], minute=values['minute_' + suffix],
            second=values['second_' + suffix], microsecond=0)
    start, end = bound('start'), bound('end')
    if start >= end:
        raise ValueError('报表结束时间必须晚于开始时间')
    return start.strftime('%Y%m%d%H%M%S'), end.strftime('%Y%m%d%H%M%S')
