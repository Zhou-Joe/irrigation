"""Aggregate readings in SQL; materialize station metadata once per response."""
from collections import defaultdict
from types import SimpleNamespace
from django.db.models import Sum
from .models import Patch


def runtime_buckets(qs):
    rows = list(qs.order_by().values('site_id', 'station_id').annotate(run_time=Sum('run_time')))
    # Metadata includes configured, non-running stations so orphan labels and
    # empty matrix cells retain the exact existing behavior.
    stations = list(Patch.objects.all().only(
        'id', 'parent_id', 'controller_number', 'controller_channel'))
    by_id = {s.pk:s for s in stations}
    by_site = defaultdict(list)
    configured = defaultdict(list)
    for st in stations:
        if st.controller_channel is not None:
            configured[st.parent_id].append(st)
    for row in rows:
        st = by_id.get(row['station_id'])
        if st:
            by_site[row['site_id']].append(SimpleNamespace(station=st, run_time=row['run_time'], site_id=row['site_id']))
    return by_site, configured
