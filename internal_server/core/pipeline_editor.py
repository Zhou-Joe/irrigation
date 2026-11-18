"""Map edits for imported devices whose CAD identity belongs to a drawing batch."""
import json

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Max
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .dxf_views import _pipeline_dxf_gate
from .models import Patch, PipeValve, Pipeline, PipelineImportBatch, Zone
from .views import _invalidate_cached


def batch_projection(batch):
    from .dxf_pipeline_utils import _local_to_latlng_fn
    snapshot = batch.applied_calibration or batch.calibration_snapshot
    if not snapshot:
        return None
    fn, _ = _local_to_latlng_fn(snapshot)
    if not fn:
        return None
    dy, dx = batch.import_options.get('offset', [0, 0])
    def project(x, y, precision=6):
        lat, lng = fn(x, y)
        return {'lat': round(lat + dy, precision), 'lng': round(lng + dx, precision)}
    return project


def pending_feature(batch, item, project):
    base = project(item['x'], item['y'])
    dy, dx = item.get('manual_offset', [0, 0])
    kind = item.get('valve_type') or batch.import_options.get('blocks', {}).get(item['block'], {}).get('valve_type')
    if not kind:
        kind = next((shape.get('valve_type') for shape in batch.source_geometry.get('recognized_shapes', [])
                     if shape['id'] == item.get('source_id')), None)
    return {**item, 'type': kind or '', 'lat': round(base['lat'] + dy, 7), 'lng': round(base['lng'] + dx, 7)}


@login_required
@require_GET
@ensure_csrf_cookie
def editor(request):
    if not _pipeline_dxf_gate(request.user):
        return JsonResponse({'error':'无权限'}, status=403)
    return render(request, 'core/pipeline_editor.html', {'valve_types':PipeValve.VALVE_TYPE_CHOICES})


@login_required
@require_POST
def edit_pending(request, batch_id):
    if not _pipeline_dxf_gate(request.user):
        return JsonResponse({'error':'无权限'}, status=403)
    try:
        lat, lng = float(request.POST['lat']), float(request.POST['lng'])
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError
        original = json.loads(request.POST['original'])
        if not isinstance(original, dict):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        return JsonResponse({'error':'设备位置无效。'}, status=400)
    pt = {'lat': round(lat, 7), 'lng': round(lng, 7)}
    sid = request.POST.get('source_id')
    with transaction.atomic():
        batch = PipelineImportBatch.objects.select_for_update().filter(pk=batch_id).first()
        if not batch or not sid:
            return JsonResponse({'error':'找不到导入设备。'}, status=404)
        source = batch.source_geometry
        pending = source.get('unmatched_valves', [])
        item = next((v for v in pending if v.get('source_id') == sid), None)
        if not item:
            return JsonResponse({'error':'设备已挂接或批次已变化，请刷新。'}, status=409)
        project = batch_projection(batch)
        if not project:
            return JsonResponse({'error':'图纸没有可用的地理定位。'}, status=400)
        current = pending_feature(batch, item, project)
        if any(current[k] != original.get(k) for k in pt):
            return JsonResponse({'error':'设备已被其他人移动，请刷新。'}, status=409)
        baseline = project(item['x'], item['y'])
        pid = request.POST.get('pipeline')
        valve = None
        if pid:
            kind = request.POST.get('type') or current['type']
            if kind not in dict(PipeValve.VALVE_TYPE_CHOICES):
                return JsonResponse({'error':'请选择阀门类型。'}, status=400)
            pipe = Pipeline.objects.select_for_update().filter(pk=pid).first() if pid.isdecimal() else None
            if not pipe:
                return JsonResponse({'error':'目标管道不存在。'}, status=400)
            zid = request.POST.get('zone', '')
            zone = Zone.objects.filter(pk=zid).first() if zid.isdecimal() else None
            if zid and not zone:
                return JsonResponse({'error':'区域不存在。'}, status=400)
            station_id = None
            diameter = pipe.main_diameter
            if zone and kind == PipeValve.VALVE_SOLENOID:
                stations = zone.maxicom_runtime
                if isinstance(stations, list) and stations and str(stations[0]).isdecimal():
                    station_id = Patch.objects.filter(pk=stations[0]).values_list('pk', flat=True).first()
                if zone.solenoid_valve_size:
                    diameter = round(zone.solenoid_valve_size * 25.4, 1)
            same_batch = batch.id == pipe.import_batch_id
            valve = PipeValve.objects.create(pipeline=pipe, zone=zone, station_id=station_id, valve_type=kind,
                point=[pt], source_point=[item['x'],item['y']] if same_batch else [],
                source_map_point=[baseline] if same_batch else [], name=(item.get('name') or item['block'])[:50],
                source_attributes={**item.get('source_attributes', {}), 'tags': item.get('attrs', {}),
                                   'source_id':sid, 'block':item['block'], 'cad_batch_id':batch.pk},
                diameter=diameter, order=(pipe.valves.aggregate(n=Max('order'))['n'] or 0)+1)
            pending.remove(item)
        else:
            item['manual_offset'] = [pt[k]-baseline[k] for k in ('lat','lng')]
        batch.save(update_fields=['source_geometry'])
        transaction.on_commit(lambda: _invalidate_cached('dashboard:pipelines'))
    return JsonResponse({'success':True, 'valve_id':valve.pk if valve else None})
