"""Normalize Maxicom hourly weather at import, then aggregate observed days.

XA_WETHR uses Fahrenheit, inches (rain/ET), miles (wind run), percent humidity
and Langleys (solar). Existing model fields are kept in Celsius/mm/km/Ly so
the dashboard, AI data and Excel share one conversion, never two.
"""
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone as datetime_timezone
from zoneinfo import ZoneInfo

from django.db import transaction

from .models import MaxicomWeatherLog, MaxicomWeatherStation

SHANGHAI = ZoneInfo('Asia/Shanghai')
INCH_MM = 25.4
MILE_KM = 1.609344
WEATHER_FIELDS = ('temperature', 'max_temp', 'min_temp', 'solar_radiation',
                  'rainfall', 'humidity', 'wind_run', 'et')
# Audited source: hourly ET is unpopulated, XA_ET is a monthly reference, and
# Site soil-checkbook ET is not proven reference ET0. Preserve observed hourly
# values in storage, but never present them as verified daily ET0 in the report.
REPORT_ET0_VERIFIED = False


def _clean(value):
    value = '' if value is None else str(value).strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1]
    return value


def _number(value):
    if value is None or isinstance(value, bool) or _clean(value) == '':
        return None
    try:
        value = float(_clean(value))
    except (ValueError, TypeError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _temperature(value):
    value = _number(value)
    if value is None or not -120 <= value <= 180:
        return None
    return (value - 32) * (5 / 9)


def _positive(value, factor=1):
    value = _number(value)
    return value * factor if value is not None and value >= 0 else None


def parse_weather_row(row):
    """Return one SI hourly reading, preserving the exact raw UTC poll stamp."""
    try:
        index = int(_clean(row.get('XactIndex')))
        stamp = _clean(row.get('XactStamp'))
        if index <= 0 or len(stamp) != 14 or not stamp.isdigit():
            return None
        datetime.strptime(stamp, '%Y%m%d%H%M%S')
    except (ValueError, TypeError, OverflowError):
        return None
    humidity = _number(row.get('Humidity'))
    if humidity is not None and not 0 <= humidity <= 100:
        humidity = None
    return {'source_index': index, 'timestamp': stamp,
            'temperature': _temperature(row.get('Temperature')),
            'max_temp': _temperature(row.get('MaxTemp')),
            'min_temp': _temperature(row.get('MinTemp')),
            'solar_radiation': _positive(row.get('SolarRadiation')),
            'rainfall': _positive(row.get('RainFall'), INCH_MM),
            'humidity': humidity, 'wind_run': _positive(row.get('WindRun'), MILE_KM),
            'et': _positive(row.get('ET'), INCH_MM)}


def station_defaults(row, index):
    return {'name': _clean(row.get('IndexName'))[:255] or f'气象站 {index}',
            'time_zone': _clean(row.get('WeatherTimeZone'))[:50] or 'China',
            'default_et': _positive(row.get('WeatherDefaultET'), INCH_MM)}


def import_weather(mdb_path, read_rows, stdout=None):
    """Read a complete backup before transactionally replacing weather logs.

    No hourly ET is fabricated from a station's default_et. A failed/empty
    parse cannot delete an existing weather history. Repeated source stamps
    are corrections to one hourly observation, not extra rainfall or ET.
    """
    from .flow_import import latest_config
    configs = latest_config(read_rows(mdb_path, 'WETHR_CF'))
    parsed, empty_rows, duplicates = {}, 0, 0
    for raw in read_rows(mdb_path, 'XA_WETHR'):
        if not raw or not any(_clean(value) for value in raw.values()):
            empty_rows += 1
            continue
        row = parse_weather_row(raw)
        if row is None:
            raise ValueError('天气备份包含无效站点或时间戳，未替换原天气历史。请检查原始备份。')
        key = row['source_index'], row['timestamp']
        if key in parsed:
            duplicates += 1
        parsed[key] = row
    if not parsed and MaxicomWeatherLog.objects.exists():
        raise ValueError('备份中没有可读取的实际天气记录，原天气历史已保留。')
    station_indices = set(configs) | {key[0] for key in parsed}
    with transaction.atomic():
        stations = {}
        for index in sorted(station_indices):
            stations[index], _ = MaxicomWeatherStation.objects.update_or_create(mdb_index=index,
                defaults=station_defaults(configs.get(index, {}), index))
        MaxicomWeatherLog.objects.all().delete()
        batch = []
        for row in parsed.values():
            values = {field: row[field] for field in WEATHER_FIELDS}
            batch.append(MaxicomWeatherLog(weather_station=stations[row['source_index']],
                                           timestamp=row['timestamp'], **values))
            if len(batch) >= 1000:
                MaxicomWeatherLog.objects.bulk_create(batch, batch_size=1000)
                batch.clear()
        if batch:
            MaxicomWeatherLog.objects.bulk_create(batch, batch_size=1000)
    if stdout is not None:
        stdout.write(f'Weather: {len(parsed)} hourly readings, {len(stations)} stations; '
                     f'{empty_rows} empty rows ignored, {duplicates} repeated stamps deduplicated; stored °C/mm/km/Ly')
    return len(parsed)


def _local_stamp(raw):
    return datetime.strptime(raw, '%Y%m%d%H%M%S').replace(tzinfo=datetime_timezone.utc).astimezone(SHANGHAI)


def _day_record(rows):
    """Hourly min/max, mean humidity, and additive observed interval totals."""
    output, missing = {}, []
    for field in ('min_temp', 'max_temp', 'humidity', 'solar_radiation', 'wind_run', 'rainfall', 'et'):
        if field == 'et' and not REPORT_ET0_VERIFIED:
            output[field] = None
            continue
        values = [row[field] for row in rows if _number(row.get(field)) is not None]
        if len(values) != len(rows):
            missing.append({'min_temp': '低温', 'max_temp': '高温', 'humidity': '湿度',
                'solar_radiation': '光照', 'wind_run': '风程', 'rainfall': '降雨', 'et': 'ET0'}[field])
        if not values:
            output[field] = None
        elif field == 'min_temp':
            output[field] = min(values)
        elif field == 'max_temp':
            output[field] = max(values)
        elif field == 'humidity':
            output[field] = sum(values) / len(values)
        else:
            output[field] = sum(values)
    hours = len({_local_stamp(row['timestamp']).strftime('%Y%m%d%H') for row in rows})
    notes = []
    if hours < 24:
        notes.append(f'部分记录：{hours}/24 小时')
    if missing:
        notes.append('部分小时缺少' + '、'.join(missing))
    if not REPORT_ET0_VERIFIED:
        notes.append('ET0 缺少可核实数据')
    output['notes'] = '；'.join(notes)
    output['observed_hours'] = hours
    output['complete'] = hours == 24 and not missing
    output['source_timestamps'] = [row['timestamp'] for row in rows]
    return output


def weather_report_data(start, end):
    """Return per-station daily metric values; never combine different stations."""
    local_start = datetime(start.year, start.month, start.day, tzinfo=SHANGHAI)
    local_end = datetime(end.year, end.month, end.day, tzinfo=SHANGHAI) + timedelta(days=1)
    stamp_from = local_start.astimezone(datetime_timezone.utc).strftime('%Y%m%d%H%M%S')
    stamp_to = local_end.astimezone(datetime_timezone.utc).strftime('%Y%m%d%H%M%S')
    rows = MaxicomWeatherLog.objects.filter(timestamp__gte=stamp_from, timestamp__lt=stamp_to).order_by('timestamp', 'pk')
    grouped = defaultdict(dict)
    for row in rows.values('weather_station_id', 'timestamp', *WEATHER_FIELDS):
        try:
            day = _local_stamp(row['timestamp']).date()
        except (ValueError, TypeError):
            continue
        # A retained legacy duplicate of the same stamp is never counted twice.
        grouped[(row['weather_station_id'], day)][row['timestamp']] = row
    by_station = defaultdict(dict)
    for (station, day), values in grouped.items():
        by_station[station][day] = _day_record(list(values.values()))
    stations = []
    for station in MaxicomWeatherStation.objects.filter(pk__in=by_station).order_by('mdb_index'):
        days = by_station[station.pk]
        partial = sum(1 for row in days.values() if not row['complete'])
        count = (end - start).days + 1
        notice = f'所选 {count} 天中有 {len(days)} 天实际记录'
        if partial:
            notice += f'，其中 {partial} 天记录不完整'
        if len(days) < count:
            notice += '；其余日期缺测留空'
        stations.append({'id': station.pk, 'mdb_index': station.mdb_index,
                         'name': station.name, 'days': days, 'notice': notice + '。'})
    return {'stations': stations,
        'notice': '' if stations else '所选日期没有 Maxicom 实际天气记录；空白不表示无降雨或 ET0 为 0。',
        'source_note': '来源：Rain Bird Maxicom 实际小时气象记录，按上海自然日汇总。低温取小时最低值，高温取小时最高值，湿度取有效小时均值；光照、风程、降雨累计小时值。原始 °F/英寸/英里在导入时统一换算为 °C/mm/km，光照保留 Ly。'
            + ('ET0 由已核实的实际来源累计。' if REPORT_ET0_VERIFIED else '原数据没有可核实的 ET0，该列留空；未用默认值、月参考值、土壤账本或重新计算值补齐。')}
