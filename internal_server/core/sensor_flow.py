"""Physical Rain Bird sensors: XA_LOG D/F, never FLO WATCH zone totals.

SignalValue counts pulses; SignalMultiplier is the calibration logged with that
reading (gallons/pulse). Maxicom's metric calibration uses 3.785 liters/gallon:
18.494055 -> 70 L/pulse, 52.840157 -> 200 L/pulse. Keep micro-units internally,
round only at presentation. Never substitute today's calibration for old logs.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import struct
import subprocess
import zlib

from django.core.management.base import CommandError
from django.db import transaction
from django.db.models import Q, Sum

from core.flow_data import SAMPLE, encode_samples, sample_offset_for_hour, sum_samples
from core.irrig_time import irrigation_day_for_utc, irrigation_day_utc_bounds, runtime_window_bounds
from core.models import MaxicomFlowSensor, MaxicomSensorDaily

MICRO = Decimal(1_000_000)
LITERS_PER_SOURCE_GALLON = Decimal('3.785')


def pulse_microliters(value, multiplier):
    pulses = int(value)
    factor = Decimal(str(multiplier))
    if pulses < 0 or not factor.is_finite() or factor <= 0:
        raise ValueError('Invalid sensor pulse/calibration')
    return int((pulses * factor * LITERS_PER_SOURCE_GALLON * MICRO).quantize(
        Decimal(1), rounding=ROUND_HALF_UP))


def import_sensor_flow(mdb_path, read_rows, process_factory, stdout):
    from core.flow_import import latest_config
    sites = latest_config(read_rows(mdb_path, 'SITE_CF'))
    types = {int(r['IndexNumber']) for r in read_rows(mdb_path, 'DCODE_TP')
             if r.get('DecoderTypeFlowMeter', '').strip().upper() == 'Y'}
    configs = latest_config(read_rows(mdb_path, 'DCODE_CF'))
    metadata = {}
    try:
        for index, row in configs.items():
            if int(row.get('TableIndexNumber') or 0) not in types:
                continue
            source = int(row['DecoderSiteNumber'])
            site = sites[source]
            metadata[index] = {
                'name': row.get('IndexName', '').strip() or f'Sensor {index}',
                'source_site_index': source,
                'source_site_number': int(site['SiteNumber']) if site.get('SiteNumber') else None,
                'source_site_name': site.get('IndexName', '').strip(),
                'controller_number': int(row['DecoderControllerNumber']) if row.get('DecoderControllerNumber') else None,
                'channel': int(row['DecoderControllerChannel']) if row.get('DecoderControllerChannel') else None,
                'is_active': not bool(row.get('DateClose')),
                'is_enabled': row.get('DecoderEnabled', '').strip().upper() == 'Y',
            }
    except (KeyError, ValueError, TypeError) as exc:
        raise CommandError('Invalid sensor configuration; previous data preserved') from exc
    if not metadata:
        raise CommandError('No flow sensor configuration; previous data preserved')

    totals = defaultdict(lambda: [0, 0, bytearray()])
    hours = {}
    start = end = ''
    count = 0
    proc = process_factory(['mdb-export', '-Q', '-d', '|', mdb_path, 'XA_LOG'],
                           stdout=subprocess.PIPE, text=True)
    error = None
    try:
        columns = {s: i for i, s in enumerate(proc.stdout.readline().strip().split('|'))}
        required = ['XactStamp', 'XactIndex', 'SignalTable', 'SignalType', 'SignalValue', 'SignalMultiplier']
        if not all(c in columns for c in required):
            raise ValueError('Missing sensor export columns')
        for line in proc.stdout:
            fields = line.rstrip('\r\n').split('|')
            table, kind = fields[columns['SignalTable']], fields[columns['SignalType']]
            if (table, kind) not in (('S', 'M'), ('D', 'F')):
                continue
            stamp = fields[columns['XactStamp']]
            hour = stamp[:10]
            if len(stamp) != 14 or not stamp.isdigit():
                raise ValueError('Invalid sensor export timestamp')
            if hour not in hours:
                hours[hour] = sample_offset_for_hour(hour)
            minute, second = int(stamp[10:12]), int(stamp[12:14])
            if minute > 59 or second > 59:
                raise ValueError('Invalid sensor export timestamp')
            start, end = min(start or stamp, stamp), max(end or stamp, stamp)
            if (table, kind) != ('D', 'F'):
                continue
            index = int(fields[columns['XactIndex']])
            if index not in metadata:
                raise ValueError('Unknown flow sensor reference')
            volume = pulse_microliters(fields[columns['SignalValue']], fields[columns['SignalMultiplier']])
            day, base = hours[hour]
            total = totals[(day, index)]
            total[0] += volume
            total[1] += 1
            total[2].extend(SAMPLE.pack(base + minute * 60 + second, volume))
            count += 1
    except (ValueError, TypeError, IndexError, OverflowError, InvalidOperation, struct.error) as exc:
        error = str(exc)
        proc.terminate()
    finally:
        proc.stdout.close()
        status = proc.wait()
    if error or status or not start or (not count and MaxicomSensorDaily.objects.exists()):
        raise CommandError(f'Sensor export failed ({error or status or "empty"}); previous data preserved')

    with transaction.atomic():
        MaxicomFlowSensor.objects.all().update(is_active=False)
        saved = {}
        for index, defaults in metadata.items():
            defaults.update(coverage_start=start, coverage_end=end)
            saved[index], _ = MaxicomFlowSensor.objects.update_or_create(mdb_index=index, defaults=defaults)
        MaxicomSensorDaily.objects.all().delete()
        batch = []
        for (day, index), (volume, number, samples) in totals.items():
            batch.append(MaxicomSensorDaily(sensor=saved[index], flow_day=day, microliters=volume,
                sample_count=number, samples=encode_samples(samples)))
            if len(batch) >= 1000:
                MaxicomSensorDaily.objects.bulk_create(batch, batch_size=1000)
                batch.clear()
        if batch:
            MaxicomSensorDaily.objects.bulk_create(batch, batch_size=1000)
    stdout.write(f'Sensors: {len(saved)} physical meters, {count} timed pulse readings')


def sensor_window(local_from, local_to):
    start, end = runtime_window_bounds(local_from, local_to)
    result = {'sites': [], 'notice': '', 'unit': 'L', 'unit_verified': True,
              'source': 'Rain Bird 实际流量传感器（XA_LOG D/F）'}
    if not start or not end:
        result['notice'] = '请选择开始和结束时间。'
        return result
    first, last = irrigation_day_for_utc(start), irrigation_day_for_utc(end)
    totals = defaultdict(int)
    samples = defaultdict(int)
    first_start, _ = irrigation_day_utc_bounds(first, first)
    _, last_end = irrigation_day_utc_bounds(last, last)
    full_start = first if start <= first_start else first + timedelta(days=1)
    full_end = last if end >= last_end else last - timedelta(days=1)
    if full_start <= full_end:
        for row in MaxicomSensorDaily.objects.filter(
                flow_day__range=(full_start.strftime('%Y%m%d'), full_end.strftime('%Y%m%d'))
                ).values('sensor_id').annotate(total=Sum('microliters')):
            totals[row['sensor_id']] += row['total']
            samples[row['sensor_id']] += 1
    partial_days = {d.strftime('%Y%m%d') for d in (first, last) if not full_start <= d <= full_end}
    try:
        for row in MaxicomSensorDaily.objects.filter(flow_day__in=partial_days
                ).values('sensor_id', 'flow_day', 'samples'):
            totals[row['sensor_id']] += sum_samples(row['samples'], row['flow_day'], start, end)
            samples[row['sensor_id']] += 1
    except (ValueError, zlib.error, struct.error):
        result['notice'] = '传感器记录不完整，请重新同步后查询。'
        return result
    sites = {}
    sensors = MaxicomFlowSensor.objects.filter(Q(is_active=True) | Q(pk__in=totals)).order_by('source_site_number', 'channel', 'mdb_index')
    for sensor in sensors:
        complete = bool(sensor.coverage_start and sensor.coverage_start <= start <= end <= sensor.coverage_end)
        value = totals[sensor.pk] if (complete and sensor.is_enabled) or sensor.pk in samples else None
        liters = Decimal(value) / MICRO if value is not None else None
        display = liters.quantize(Decimal('.01'), rounding=ROUND_HALF_UP) if liters is not None else None
        formatted = ('—' if display is None else f'{display:,.0f}' if display == display.to_integral() else f'{display:,.2f}')
        key = str(sensor.source_site_index)
        site = sites.setdefault(key, {'key': key, 'number': sensor.source_site_number,
            'label': f'Site {sensor.source_site_number}' if sensor.source_site_number is not None else '未编号 Site',
            'name': sensor.source_site_name, 'sensors': []})
        site['sensors'].append({'index': sensor.mdb_index, 'channel': sensor.channel, 'name': sensor.name,
            'value': float(display) if display is not None else None, 'formatted': formatted,
            'complete': complete, 'enabled': sensor.is_enabled})
    result['sites'] = list(sites.values())
    if not sites:
        result['notice'] = '实际流量传感器尚未同步。'
    elif any(not s['complete'] for site in result['sites'] for s in site['sensors']):
        result['coverage_note'] = '所选时段超出备份覆盖范围，已显示的读数仅为部分记录，— 表示无法确认。'
    return result
