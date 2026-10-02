"""DXF 管线导入 + 管网精细编辑视图（自 core/views.py 按功能拆出）。

URL 绑定见 core/urls.py；页面模板 templates/core/pipeline_dxf_import.html，
前端脚本 static/js/dxf-import/。权限门槛统一走 _pipeline_dxf_gate。
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import ensure_csrf_cookie

from core.views import _invalidate_cached, _get_reference_map_data, json_html_safe


def _pipeline_dxf_gate(user):
    """Manager-tier gate shared by the DXF pipeline import page + endpoints."""
    from .models import ManagerProfile
    if user.is_superuser or user.is_staff:
        return True
    return ManagerProfile.objects.filter(user=user, active=True).exists()


@login_required(login_url='core:login')
@ensure_csrf_cookie
def pipeline_dxf_import(request):
    """Dedicated page: import a CAD (DXF) irrigation drawing into Pipeline/PipeValve.

    Flow (all client-orchestrated): upload → ``pipeline_dxf_analyze`` returns
    layer/block/label census + preview geometry → the user maps layers to
    diameters and blocks to valve types on a Leaflet preview →
    ``pipeline_dxf_import_submit`` creates the rows.
    """
    if not _pipeline_dxf_gate(request.user):
        messages.error(request, '无权限')
        return redirect('core:dashboard')
    ref_zones_json, ref_pipelines_json = _get_reference_map_data()
    from core.dxf_pipeline_utils import active_calibration_info
    from core.calibration import SITE_CALIBRATION_POINTS
    from core.models import PipelineImportBatch
    return render(request, 'core/pipeline_dxf_import.html', {
        'ref_zones_json': ref_zones_json,
        'ref_pipelines_json': ref_pipelines_json,
        'dxf_calibration_json': json_html_safe(active_calibration_info()),
        'dxf_placement_points_json': json_html_safe(SITE_CALIBRATION_POINTS),
        'import_batches': PipelineImportBatch.objects.only('id', 'name', 'source_token'),
    })


@require_POST
@login_required(login_url='core:login')
def pipeline_dxf_analyze(request):
    """AJAX: parse an uploaded DXF, return layer/block/label overview + preview.

    With no ``file`` but a valid ``token`` (from a previous analyze within the
    parse-cache TTL) it rebuilds the preview from cache — used after saving a
    new site calibration so the overlay re-renders without re-upload.
    """
    from core.dxf_pipeline_utils import analyze_dxf_pipelines
    if not _pipeline_dxf_gate(request.user):
        return JsonResponse({'success': False, 'error': '无权限'}, status=403)
    f = request.FILES.get('file')
    token = (request.POST.get('token') or '').strip()
    if not f and not token:
        return JsonResponse({'success': False, 'error': '请上传 .dxf 文件'}, status=400)
    if f and not f.name.lower().endswith('.dxf'):
        return JsonResponse({'success': False, 'error': '请上传 .dxf 文件'}, status=400)
    try:
        return JsonResponse(analyze_dxf_pipelines(f or None, token=token or None, user_id=request.user.pk,
                    calibration_id=request.POST.get('calibration_id') or None))
    except Exception:
        import logging
        logging.getLogger(__name__).exception('DXF analyze failed')
        return JsonResponse({'success': False, 'error': 'DXF 解析失败，请确认文件是标准 DXF 格式'}, status=400)


def _cal_pairs_from_post(request, field='pairs', minimum=2):
    """校准端点共用：解析并验证 POST 的 pairs JSON（原始 DXF 坐标）。

    返回 (pairs, err)。点数 2..300，字段全部转 float 且必须有限，卫星点
    经纬度限合法范围 — json.loads 接受 NaN/Infinity 字面量且拟合不会拒绝
    它们，一条毒化的标定会全局破坏坐标转换，必须在这里拦下。
    """
    import json as _json
    import math as _math
    try:
        raw = _json.loads(request.POST.get(field) or '[]')
    except (ValueError, TypeError):
        return None, 'pairs 不是合法 JSON'
    if not isinstance(raw, list) or not (minimum <= len(raw) <= 300):
        return None, f'{field} 需包含 {minimum} 到 300 个点'
    pairs = []
    for p in raw:
        try:
            vals = {k: float(p[k]) for k in ('dxf_x', 'dxf_y', 'lat', 'lng')}
        except (KeyError, TypeError, ValueError):
            return None, '标定点字段缺失或非数值'
        if not all(_math.isfinite(v) for v in vals.values()):
            return None, '标定点包含 NaN/Infinity 等非有限数值'
        if not (-90 <= vals['lat'] <= 90) or not (-180 <= vals['lng'] <= 180):
            return None, '卫星点经纬度超出合法范围（lat ±90 / lng ±180）'
        pairs.append(vals)
    return pairs, None


@require_POST
@login_required(login_url='core:login')
def pipeline_dxf_calibration_save(request):
    """Validate and save a drawing-scoped calibration, retaining history."""
    from core.calibration import fit_calibration_transform
    from core.models import SiteCalibration
    from core.dxf_state import calibration_snapshot
    from core.dxf_pipeline_utils import _bust_calibration_cache, active_calibration_info
    if not _pipeline_dxf_gate(request.user):
        return JsonResponse({'success': False, 'error': '无权限'}, status=403)
    pairs, err = _cal_pairs_from_post(request, minimum=3)
    if err:
        return JsonResponse({'success': False, 'error': err}, status=400)
    method = (request.POST.get('method') or 'sim').strip()
    if method != 'sim':
        return JsonResponse({'success': False, 'error': '只支持保持 CAD 比例的控制点对齐；旧变形方法已停用'}, status=400)
    checks, err = _cal_pairs_from_post(request, 'check_points', minimum=1)
    if err:
        return JsonResponse({'success': False, 'error': err}, status=400)
    cal = [{'dxf_x': p['dxf_x'], 'dxf_y': -p['dxf_y'], 'lat': p['lat'], 'lng': p['lng']}
           for p in pairs]
    fn, stats = fit_calibration_transform(cal, method or None)
    if not callable(fn):
        return JsonResponse({'success': False, 'error': stats or '标定点退化'}, status=400)
    from core.dxf_state import alignment_status
    alignment = alignment_status({'points': pairs, 'check_points': checks, 'method': method})
    if not alignment['ready']:
        return JsonResponse({'success': False, 'error': alignment['error'], 'alignment': alignment}, status=400)
    drawing_token = (request.POST.get('token') or '').strip()
    batch_id = request.POST.get('batch_id')
    if not drawing_token and not batch_id:
        return JsonResponse({'success': False, 'error': '请先上传图纸或选择导入批次'}, status=400)
    if batch_id:
        from core.models import PipelineImportBatch
        try:
            batch = PipelineImportBatch.objects.filter(pk=int(batch_id)).first()
        except (TypeError, ValueError):
            batch = None
        if batch is None:
            return JsonResponse({'success': False, 'error': '导入批次不存在'}, status=400)
        if drawing_token and drawing_token != batch.source_token:
            return JsonResponse({'success': False, 'error': '图纸与导入批次不一致'}, status=400)
        drawing_token = batch.source_token
    if drawing_token and not batch_id:
        from core.dxf_pipeline_utils import _parse_cache, PARSE_CACHE_KEY_PREFIX
        if _parse_cache().get(PARSE_CACHE_KEY_PREFIX + drawing_token) is None:
            return JsonResponse({'success': False, 'error': '图纸预览已过期，请重新解析'}, status=400)
    row = SiteCalibration.objects.create(
        points=pairs, check_points=checks, drawing_token=drawing_token,
        method=method,
        note=(request.POST.get('note') or '').strip()[:200],
        created_by=request.user if request.user.is_authenticated else None,
    )
    _bust_calibration_cache()
    info = active_calibration_info(calibration_snapshot(calibration_id=row.pk))
    return JsonResponse({'success': True, 'calibration': info})


@require_POST
@login_required(login_url='core:login')
def pipeline_dxf_calibration_clear(request):
    """Reset active calibration selection, retaining historical batch transforms."""
    from core.models import SiteCalibration
    from core.dxf_state import calibration_snapshot
    from core.dxf_pipeline_utils import _bust_calibration_cache, active_calibration_info
    if not _pipeline_dxf_gate(request.user):
        return JsonResponse({'success': False, 'error': '无权限'}, status=403)
    rows = SiteCalibration.objects.filter(is_active=True)
    drawing_token = (request.POST.get('token') or '').strip()
    rows = rows.filter(drawing_token=drawing_token)
    cleared = rows.update(is_active=False)
    if drawing_token and not SiteCalibration.objects.filter(drawing_token=drawing_token).exists():
        # An inactive scoped marker prevents falling back to an unrelated legacy
        # site-wide calibration after a drawing-specific reset.
        SiteCalibration.objects.create(points=[], is_active=False,
                                       drawing_token=drawing_token, note='重置图纸标定',
                                       created_by=request.user)
    _bust_calibration_cache()
    return JsonResponse({
        'success': True,
        'deleted': 0, 'cleared': cleared,
        'message': f'已重置 {cleared} 条生效标定，历史记录与已导入管道保留，请重新解析图纸',
        'calibration': active_calibration_info(calibration_snapshot(drawing_token or None)),
    })


@require_POST
@login_required(login_url='core:login')
def pipeline_dxf_calibration_apply(request):
    """Apply a selected calibration to imported batches using retained CAD coordinates."""
    import json
    from core.dxf_reproject import apply_calibration
    from core.dxf_pipeline_utils import _bust_calibration_cache
    if not _pipeline_dxf_gate(request.user):
        return JsonResponse({'success': False, 'error': '无权限'}, status=403)
    if request.POST.get('confirm') != '1':
        return JsonResponse({'success': False, 'error': '缺少确认参数'}, status=400)
    try:
        from .dxf_state import calibration_snapshot, require_alignment
        if not request.POST.get('calibration_id') or 'batch_ids' not in request.POST:
            raise ValueError('请选择已验证的标定和要重新定位的批次')
        require_alignment(calibration_snapshot(calibration_id=request.POST['calibration_id']))
        batch_ids = None
        if 'batch_ids' in request.POST:
            raw = json.loads(request.POST['batch_ids'])
            if not isinstance(raw, list) or not raw or any(type(i) is not int for i in raw):
                raise ValueError('请选择有效的导入批次')
            batch_ids = raw
        result = apply_calibration(request.POST.get('calibration_id') or None,
                                   batch_ids, request.POST.get('force') == '1', discard_legacy_offset=True)
    except (ValueError, TypeError, KeyError) as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)
    except OSError:
        return JsonResponse({'success': False, 'error': '备份写入失败，未修改任何坐标'}, status=500)
    if result.get('success'):
        _invalidate_cached('dashboard:pipelines')
        _bust_calibration_cache()
    return JsonResponse(result, status=200 if result.get('success') else 400)


@require_POST
@login_required(login_url='core:login')
def pipeline_dxf_import_submit(request):
    """AJAX: create Pipeline + PipeValve rows from the DXF per the user's mapping.

    POST: ``file`` (re-uploaded), ``layers_json`` {layer: {include, diameter,
    type}}, ``blocks_json`` {block: {include, valve_type}}, ``label_layers``
    (JSON list — which text layers may name valves).
    """
    import json as _json
    from core.dxf_pipeline_utils import import_dxf_pipelines
    if not _pipeline_dxf_gate(request.user):
        return JsonResponse({'success': False, 'error': '无权限'}, status=403)
    f = request.FILES.get('file')   # 可选：有解析缓存 token 时不需重传文件
    token = (request.POST.get('token') or '').strip() or None
    if not f and not token:
        return JsonResponse({'success': False, 'error': '缺少文件'}, status=400)
    try:
        layer_specs = _json.loads(request.POST.get('layers_json') or '{}')
        block_specs = _json.loads(request.POST.get('blocks_json') or '{}')
        label_layers = _json.loads(request.POST.get('label_layers') or '[]')
    except (_json.JSONDecodeError, TypeError):
        return JsonResponse({'success': False, 'error': '映射参数格式无效'}, status=400)
    if not isinstance(layer_specs, dict) or not any(
            isinstance(spec, dict) and spec.get('include') for spec in layer_specs.values()):
        return JsonResponse({'success': False, 'error': '请至少选择一个管道图层'}, status=400)
    if not isinstance(block_specs, dict) or not isinstance(label_layers, list):
        return JsonResponse({'success': False, 'error': '映射参数格式无效'}, status=400)
    if any(layer.startswith('块·') and isinstance(spec, dict) and spec.get('include')
           for layer, spec in layer_specs.items()):
        return JsonResponse({'success': False, 'error': '块符号仅作为 CAD 参考，请在设备页选择阀门类型'}, status=400)
    preview_token = request.POST.get('preview_token') or ''
    if not preview_token:
        return JsonResponse({'success': False, 'error': '请先解析图纸并确认预览'}, status=400)
    # Older clients may send zero offsets; unverified whole-drawing shifts are retired.
    try:
        offset = (float(request.POST.get('offset_lat') or 0),
                  float(request.POST.get('offset_lng') or 0))
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'error': '偏移参数必须为有效数值'}, status=400)
    if offset != (0.0, 0.0):
        return JsonResponse({'success': False, 'error': '拖动偏移定位已停用，请使用控制点重新对齐'}, status=400)
    try:
        from .dxf_state import read_preview, require_alignment
        state = read_preview(preview_token, token, request.user.pk)
        require_alignment(state['calibration'])
        result = import_dxf_pipelines(
            layer_specs, block_specs, uploaded_file=f,
            label_layers=label_layers, offset=offset, token=token, preview_token=preview_token,
            batch_name=(f.name if f and f.name
                        else (request.POST.get('filename') or 'DXF导入')),
            imported_by=request.user if request.user.is_authenticated else None)
    except ValueError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)
    except Exception:
        # 具体异常记日志排查；对外统一话术，避免泄露服务器路径等信息
        import logging
        logging.getLogger(__name__).exception('DXF pipeline import failed')
        return JsonResponse({'success': False, 'error': '导入失败，请检查图纸格式后重试'}, status=400)
    _invalidate_cached('dashboard:pipelines')
    return JsonResponse({'success': True, **result})


# ── 管网精细编辑（DXF 导入后的单项修正：删管道/阀门、清标注、阀门配 zone）──

@login_required(login_url='core:login')
def pipeline_edit_data(request):
    """编辑模式的地图数据：全部管线 + 阀门 + zone 清单（用于指派下拉）。"""
    from .models import Pipeline, PipelineImportBatch, PipeValve, Zone
    from .dxf_pipeline_utils import active_calibration_info
    from .dxf_state import calibration_snapshot
    if not _pipeline_dxf_gate(request.user):
        return JsonResponse({'success': False, 'error': '无权限'}, status=403)
    pipes = []
    for p in (Pipeline.objects.all().order_by('id')):
        pipes.append({
            'id': p.id, 'name': p.name, 'code': p.code,
            'type': p.pipeline_type, 'type_display': p.get_pipeline_type_display(),
            'diameter': p.main_diameter, 'color': p.line_color,
            'line_points': p.line_points, 'source_points': p.source_points,
            'batch_id': p.import_batch_id, 'source': p.source_label or '',
        })
    valves = []
    for v in (PipeValve.objects.select_related('zone', 'station').order_by('id')):
        valves.append({
            'id': v.id, 'pipeline_id': v.pipeline_id,
            'name': v.name or '', 'type': v.valve_type,
            'type_display': v.get_valve_type_display(),
            'diameter': v.diameter, 'point': v.point, 'source_point': v.source_point,
            'notes': v.notes, 'source_attributes': v.source_attributes,
            'zone_id': v.zone_id, 'zone_label': (v.zone.code + ' ' + v.zone.name) if v.zone else '',
            'station_id': v.station_id,
        })
    zones = [{'id': z.id, 'label': f'{z.code} {z.name}'}
             for z in Zone.objects.order_by('code')]
    batch_calibrations = {
        str(b.id): active_calibration_info(b.applied_calibration or b.calibration_snapshot
                                          or calibration_snapshot(b.source_token or None))
        for b in PipelineImportBatch.objects.all()
    }
    cad_source = None
    cad_options = None
    if request.GET.get('batch_id'):
        try:
            batch = PipelineImportBatch.objects.get(pk=int(request.GET['batch_id']))
        except (ValueError, PipelineImportBatch.DoesNotExist):
            return JsonResponse({'success': False, 'error': '导入批次不存在'}, status=400)
        cad_source = batch.source_geometry or None
        cad_options = batch.import_options
    return JsonResponse({'success': True, 'pipelines': pipes,
                         'valves': valves, 'zones': zones,
                         'batch_calibrations': batch_calibrations, 'cad_source': cad_source,
                         'cad_options': cad_options})


@require_POST
@login_required(login_url='core:login')
def pipeline_edit_pipeline_delete(request, pipeline_id):
    """删除单条管道（阀门级联删除）。"""
    from .models import Pipeline, ManagerProfile
    if not _pipeline_dxf_gate(request.user):
        return JsonResponse({'success': False, 'error': '无权限'}, status=403)
    p = Pipeline.objects.filter(pk=pipeline_id).first()
    if not p:
        return JsonResponse({'success': False, 'error': '管道不存在'}, status=404)
    name = p.name
    p.delete()
    _invalidate_cached('dashboard:pipelines')
    return JsonResponse({'success': True, 'message': f'已删除管道「{name}」'})


@require_POST
@login_required(login_url='core:login')
def pipeline_edit_valve_delete(request, valve_id):
    """删除单个阀门。"""
    from .models import PipeValve
    if not _pipeline_dxf_gate(request.user):
        return JsonResponse({'success': False, 'error': '无权限'}, status=403)
    v = PipeValve.objects.filter(pk=valve_id).first()
    if not v:
        return JsonResponse({'success': False, 'error': '阀门不存在'}, status=404)
    label = v.name or f'#{v.id}'
    v.delete()
    _invalidate_cached('dashboard:pipelines')
    return JsonResponse({'success': True, 'message': f'已删除阀门「{label}」'})


@require_POST
@login_required(login_url='core:login')
def pipeline_edit_geometry(request, pipeline_id):
    """逐线精调：保存一条管道的几何（line_points + 线上阀门位置）。

    POST: ``line_points``（JSON [{lat,lng}]，2..2000 点）、可选 ``valves``
    （JSON [{id, point:{lat,lng}}]，只允许该管道自己的阀门）。坐标做
    有限性/范围校验；管道穿越 zones 按新几何重算。
    """
    import json as _json
    import math as _math
    from django.db import transaction as _db_txn
    from .models import Pipeline, PipeValve
    if not _pipeline_dxf_gate(request.user):
        return JsonResponse({'success': False, 'error': '无权限'}, status=403)
    p = Pipeline.objects.filter(pk=pipeline_id).first()
    if not p:
        return JsonResponse({'success': False, 'error': '管道不存在'}, status=404)

    def _ok_pt(pt):
        try:
            lat, lng = float(pt['lat']), float(pt['lng'])
        except (KeyError, TypeError, ValueError):
            return None
        if not (_math.isfinite(lat) and _math.isfinite(lng)):
            return None
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return None
        return {'lat': round(lat, 7), 'lng': round(lng, 7)}

    try:
        raw_pts = _json.loads(request.POST.get('line_points') or '[]')
        raw_valves = _json.loads(request.POST.get('valves') or '[]')
    except (ValueError, TypeError):
        return JsonResponse({'success': False, 'error': '坐标参数不是合法 JSON'}, status=400)
    if not isinstance(raw_pts, list) or not (2 <= len(raw_pts) <= 2000):
        return JsonResponse({'success': False, 'error': 'line_points 需为 2..2000 个点'}, status=400)
    pts = [_ok_pt(pt) for pt in raw_pts]
    if any(pt is None for pt in pts):
        return JsonResponse({'success': False, 'error': '坐标点缺失或超界（lat ±90 / lng ±180）'}, status=400)
    valve_updates = []
    if isinstance(raw_valves, list):
        for it in raw_valves:
            try:
                vid = int(it['id'])
            except (KeyError, TypeError, ValueError):
                return JsonResponse({'success': False, 'error': 'valves.id 非法'}, status=400)
            if not isinstance(it.get('point'), dict):
                continue
            npt = _ok_pt(it['point'])
            if npt is None:
                return JsonResponse({'success': False, 'error': '阀门坐标超界'}, status=400)
            valve_updates.append((vid, npt))

    from .pipe_utils import detect_crossed_zones
    with _db_txn.atomic():
        p.line_points = pts
        p.save(update_fields=['line_points'])
        zids = detect_crossed_zones(pts)
        if zids is not None:
            p.zones.set(zids)
        for vid, npt in valve_updates:
            # 只动本管道的阀门，防跨线篡改
            PipeValve.objects.filter(pk=vid, pipeline=p).update(point=[npt])
    _invalidate_cached('dashboard:pipelines')
    return JsonResponse({'success': True, 'message': f'已保存「{p.name}」几何'})



@require_POST
@login_required(login_url='core:login')
def pipeline_edit_valve_update(request, valve_id):
    """更新单个阀门：name（文字标注，空=清除）、zone_id（指派区域）。

    指派 zone 时按导入同款规则自动补全配对：Maxicom station 取
    ``zone.maxicom_runtime[0]``，电磁阀口径取 zone 电磁阀尺寸（英寸×25.4），
    首页即可显示灌溉数据。"""
    from .models import PipeValve, Zone
    if not _pipeline_dxf_gate(request.user):
        return JsonResponse({'success': False, 'error': '无权限'}, status=403)
    v = PipeValve.objects.filter(pk=valve_id).first()
    if not v:
        return JsonResponse({'success': False, 'error': '阀门不存在'}, status=404)

    if 'name' in request.POST:
        v.name = (request.POST.get('name') or '').strip()[:50]
    if 'zone_id' in request.POST:
        zid = (request.POST.get('zone_id') or '').strip()
        if zid:
            z = Zone.objects.filter(pk=zid).only(
                'id', 'maxicom_runtime', 'solenoid_valve_size').first()
            if not z:
                return JsonResponse({'success': False, 'error': 'zone 不存在'}, status=400)
            v.zone = z
            mr = z.maxicom_runtime
            v.station_id = mr[0] if isinstance(mr, list) and mr else None
            if v.valve_type == PipeValve.VALVE_SOLENOID and z.solenoid_valve_size:
                v.diameter = round(z.solenoid_valve_size * 25.4, 1)
        else:
            v.zone = None
            v.station = None
    v.save()
    _invalidate_cached('dashboard:pipelines')
    return JsonResponse({'success': True,
                         'message': f'阀门「{v.name or "#" + str(v.id)}」已更新'})
