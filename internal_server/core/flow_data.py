"""Independent Maxicom flow-zone records, shared by the page and AI tools.

Retain source identities and timed readings. Never derive water from station
minutes or add two measurements of the same coverage. Numeric scale is preserved
from the existing importer pending an independent source-volume reference.
"""
import struct
import zlib
from datetime import datetime, timedelta

from django.db.models import Q, Sum

from core.irrig_time import (irrigation_day_for_utc, irrigation_day_utc_bounds,
                            runtime_window_bounds)

SAMPLE = struct.Struct('<Iq')  # seconds since UTC day-window start, original value
MAGIC = b'MCF1'


def encode_samples(samples):
    return MAGIC + zlib.compress(samples)


def sample_offset_for_hour(hour):
    day = irrigation_day_for_utc(hour)
    start, _ = irrigation_day_utc_bounds(day, day)
    offset = int((datetime.strptime(hour, '%Y%m%d%H') -
                  datetime.strptime(start, '%Y%m%d%H%M%S')).total_seconds())
    return day.strftime('%Y%m%d'), offset


def sum_samples(payload, day, utc_from, utc_to):
    payload = bytes(payload)
    if not payload.startswith(MAGIC):
        raise ValueError('Unsupported flow sample format')
    raw = zlib.decompress(payload[len(MAGIC):])
    if len(raw) % SAMPLE.size:
        raise ValueError('Incomplete flow sample record')
    date = datetime.strptime(day, '%Y%m%d').date()
    start, _ = irrigation_day_utc_bounds(date, date)
    origin = datetime.strptime(start, '%Y%m%d%H%M%S')
    lo = int((datetime.strptime(utc_from, '%Y%m%d%H%M%S') - origin).total_seconds())
    hi = int((datetime.strptime(utc_to, '%Y%m%d%H%M%S') - origin).total_seconds())
    total = 0
    for offset, value in SAMPLE.iter_unpack(raw):
        if not 0 <= offset < 86400:
            raise ValueError('Invalid flow sample offset')
        if lo <= offset <= hi:
            total += value
    return total


def flow_window(local_from, local_to):
    """Return every source zone separately; join_site affects Site totals only."""
    from core.models import MaxicomFlowDaily, MaxicomFlowZone

    utc_from, utc_to = runtime_window_bounds(local_from, local_to)
    result = {'sites': [], 'notice': '', 'unit': 'L'}
    if not utc_from or not utc_to:
        result['notice'] = '请选择开始和结束时间。'
        return result
    first, last = irrigation_day_for_utc(utc_from), irrigation_day_for_utc(utc_to)
    start_first, end_first = irrigation_day_utc_bounds(first, first)
    start_last, end_last = irrigation_day_utc_bounds(last, last)
    full_start = first if utc_from <= start_first else first + timedelta(days=1)
    full_end = last if utc_to >= end_last else last - timedelta(days=1)
    volumes = {}
    if full_start <= full_end:
        for row in (MaxicomFlowDaily.objects.filter(
                flow_day__range=(full_start.strftime('%Y%m%d'), full_end.strftime('%Y%m%d')))
                .values('zone_id').annotate(value=Sum('liters'))):
            volumes[row['zone_id']] = row['value'] or 0
    partial_days = {d for d in (first, last) if not full_start <= d <= full_end}
    if partial_days:
        for row in MaxicomFlowDaily.objects.filter(
                flow_day__in=[d.strftime('%Y%m%d') for d in partial_days]
                ).values('zone_id', 'flow_day', 'samples'):
            if row['samples'] is None:
                result['notice'] = ('这段历史流量暂只有整日汇总，无法按当前时段计算。'
                                    '完成流量数据同步后即可查询；也可选择完整灌溉日。')
                return result
            try:
                value = sum_samples(row['samples'], row['flow_day'], utc_from, utc_to)
            except (ValueError, zlib.error, struct.error):
                result['notice'] = '流量记录不完整，请重新同步后查询。'
                return result
            volumes[row['zone_id']] = volumes.get(row['zone_id'], 0) + value

    sites = {}
    zones = MaxicomFlowZone.objects.filter(Q(is_active=True) | Q(pk__in=volumes)).select_related('site')
    for zone in zones:
        key = str(zone.source_site_index) if zone.source_site_index is not None else f'legacy-{zone.site_id}'
        if key not in sites:
            number = zone.source_site_number
            sites[key] = {'key': key, 'number': number,
                          'label': f'Site {number}' if number is not None else '待同步站点',
                          'name': zone.source_site_name or (zone.site.name if zone.site_id else ''),
                          'value': None, 'zones': []}
        value = volumes.get(zone.pk)
        sites[key]['zones'].append({
            'index': zone.mdb_index, 'counter': zone.source_counter, 'name': zone.name,
            'included': zone.join_site, 'value': value,
            'formatted': f'{value:,}' if value is not None else '—'})
        if zone.join_site and value is not None:
            sites[key]['value'] = (sites[key]['value'] or 0) + value
    for site in sites.values():
        site['zones'].sort(key=lambda z: (z['counter'] if z['counter'] is not None else z['index'], z['index']))
        site['formatted'] = f'{site["value"]:,}' if site['value'] is not None else '—'
    result['sites'] = sorted(sites.values(), key=lambda s: (s['number'] is None, s['number'] or 0, s['key']))
    if not volumes:
        result['notice'] = '该时段暂无流量记录。'
    return result
