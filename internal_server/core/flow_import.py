"""Flow-only import. No writes to stations, controllers, runtime, or business data."""
import re
import struct
import subprocess
from collections import defaultdict

from django.core.management.base import CommandError
from django.db import transaction

from core.flow_data import SAMPLE, encode_samples, sample_offset_for_hour
from core.models import MaxicomFlowDaily, MaxicomFlowZone, Patch


def latest_config(rows):
    selected = {}
    for row in rows:
        try:
            index = int(row.get('IndexNumber') or 0)
        except (ValueError, TypeError):
            continue
        if index <= 0:
            continue
        rank = (not bool(row.get('DateClose')), row.get('DateOpen') or '')
        old = selected.get(index)
        if old is None or rank > old[0]:
            selected[index] = (rank, row)
    return {index: row for index, (_rank, row) in selected.items()}


def import_flow(mdb_path, read_rows, process_factory, stdout):
    sites = latest_config(read_rows(mdb_path, 'SITE_CF'))
    zones = latest_config(read_rows(mdb_path, 'FLOZO_CF'))
    if not sites or not zones:
        raise CommandError('No flow Site/zone configuration; previous flow data was preserved')
    patch_map = {int(p.code[3:]): p for p in Patch.objects.filter(code__iregex=r'^CCU\d+$')}
    metadata = {}
    for index, row in zones.items():
        try:
            source = int(row.get('FlowZoneSiteNumber') or 0)
            site = sites.get(source, {})
            number = int(site['SiteNumber']) if site.get('SiteNumber') else None
            counter = int(row['FlowZoneSiteCounter']) if row.get('FlowZoneSiteCounter') else None
        except (ValueError, TypeError):
            raise CommandError(f'Invalid flow configuration for zone {index}; data was preserved')
        metadata[index] = {
            'name': (row.get('IndexName') or '').strip() or f'Flow Zone {index}',
            'source_site_index': source, 'source_site_number': number,
            'source_site_name': (site.get('IndexName') or '').strip() or f'Source Site {source}',
            'source_counter': counter, 'site': patch_map.get(number),
            'join_site': (row.get('FlowZoneJoinSite') or '').strip().upper() == 'Y',
            'is_active': not bool(row.get('DateClose')),
        }

    # Sparse fixed-width samples use ~12 bytes/reading before compression. This
    # retains precise windows without millions of additional ORM rows/indexes.
    totals = defaultdict(lambda: [0, 0, bytearray()])
    hours = {}
    count = 0
    proc = process_factory(['mdb-export', '-Q', '-d', '|', mdb_path, 'XA_FLOZO'],
                           stdout=subprocess.PIPE, text=True)
    error = None
    try:
        columns = {name: n for n, name in enumerate(proc.stdout.readline().strip().split('|'))}
        required = ['XactStamp', 'XactIndex', 'FlowZoneValue', 'FlowZoneMultiplier', 'SiteID']
        if not all(name in columns for name in required):
            raise ValueError('Missing flow export columns')
        for line in proc.stdout:
            fields = line.rstrip('\r\n').split('|')
            stamp = fields[columns['XactStamp']]
            index = int(fields[columns['XactIndex']])
            source = int(fields[columns['SiteID']])
            value = int(fields[columns['FlowZoneValue']] or 0)
            multiplier = int(fields[columns['FlowZoneMultiplier']] or 1)
            if not re.fullmatch(r'\d{14}', stamp):
                raise ValueError('Invalid flow timestamp')
            minute, second = int(stamp[10:12]), int(stamp[12:14])
            if minute > 59 or second > 59:
                raise ValueError('Invalid flow timestamp')
            if index not in metadata or metadata[index]['source_site_index'] != source:
                raise ValueError('Unknown or inconsistent flow-zone Site reference')
            hour = stamp[:10]
            if hour not in hours:
                hours[hour] = sample_offset_for_hour(hour)
            day, base = hours[hour]
            volume = value * multiplier
            bucket = totals[(day, index)]
            bucket[0] += volume
            bucket[1] += value > 0
            bucket[2].extend(SAMPLE.pack(base + minute * 60 + second, volume))
            count += 1
    except (ValueError, TypeError, IndexError, OverflowError, struct.error) as exc:
        error = str(exc)
        proc.terminate()
    finally:
        proc.stdout.close()
        status = proc.wait()
    if error or status:
        raise CommandError(f'Flow export failed ({error or status}); previous flow data was preserved')
    if not count and MaxicomFlowDaily.objects.exists():
        raise CommandError('Empty flow export; previous flow data was preserved')

    with transaction.atomic():
        # Preserve zone IDs and any legacy raw-reading relations. Source keys are
        # separate from geographic Patch IDs, including unmatched and shared Sites.
        MaxicomFlowZone.objects.all().update(is_active=False)
        saved = {}
        for index, defaults in metadata.items():
            zone, _ = MaxicomFlowZone.objects.update_or_create(mdb_index=index, defaults=defaults)
            saved[index] = zone
        MaxicomFlowDaily.objects.all().delete()
        batch = []
        days = len(totals)
        while totals:
            (day, index), (volume, minutes, samples) = totals.popitem()
            zone = saved[index]
            batch.append(MaxicomFlowDaily(flow_day=day, zone=zone, site_id=zone.site_id,
                                          liters=volume, minutes=minutes, samples=encode_samples(samples)))
            if len(batch) >= 1000:
                MaxicomFlowDaily.objects.bulk_create(batch, batch_size=1000)
                batch.clear()
        if batch:
            MaxicomFlowDaily.objects.bulk_create(batch, batch_size=1000)
    stdout.write(f'Flow: {len(saved)} source zones, {days} zone-days, {count} timed readings; '
                 'station runtime unchanged by flow import')
