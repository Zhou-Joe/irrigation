"""DXF 管线导入 + 管网精细编辑视图（自 core/views.py 按功能拆出）。

URL 绑定见 core/urls.py；页面模板 templates/core/pipeline_dxf_import.html，
前端脚本 static/js/dxf-import/。权限门槛统一走 _pipeline_dxf_gate。
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from core.views import _invalidate_cached, _get_reference_map_data, json_html_safe


def _pipeline_dxf_gate(user):
    """Manager-tier gate shared by the DXF pipeline import page + endpoints."""
    from .models import ManagerProfile
    if user.is_superuser or user.is_staff:
        return True
    return ManagerProfile.objects.filter(user=user, active=True).exists()


@login_required(login_url='core:login')
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
    return render(request, 'core/pipeline_dxf_import.html', {
        'ref_zones_json': ref_zones_json,
        'ref_pipelines_json': ref_pipelines_json,
        'dxf_calibration_json': json_html_safe(active_calibration_info()),
    })


@require_POST
@login_required(login_url='core:login')
def pipeline_dxf_analyze(request):
    """AJAX: parse an uploaded DXF, return layer/block/label overview + preview.

    With no ``file`` but a valid ``token`` (from a previous analyze within the
    parse-cache TTL) it rebuilds the preview from cache — used after saving a
    new site calibration so the overlay re-renders without re-upload.
    """
    import json as _json
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
        return JsonResponse(analyze_dxf_pipelines(f or None, token=token or None))
    except Exception:
        import logging
        logging.getLogger(__name__).exception('DXF analyze failed')
        return JsonResponse({'success': False, 'error': 'DXF 解析失败，请确认文件是标准 DXF 格式'}, status=400)


def _cal_pairs_from_post(request):
    """校准端点共用：解析并验证 POST 的 pairs JSON（原始 DXF 坐标）。

    返回 (pairs, err)。点数 2..10，字段全部转 float 且必须有限，卫星点
    经纬度限合法范围 — json.loads 接受 NaN/Infinity 字面量且拟合不会拒绝
    它们，一条毒化的标定会全局破坏坐标转换，必须在这里拦下。
    """
    import json as _json
    import math as _math
    try:
        raw = _json.loads(request.POST.get('pairs') or '[]')
    except (ValueError, TypeError):
        return None, 'pairs 不是合法 JSON'
    if not isinstance(raw, list) or not (2 <= len(raw) <= 300):
        return None, '标定点数量需在 2 到 300 之间（TPS 建议 ≥6 点且撒满园区）'
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
    """AJAX: 保存用户三点校准（DXF→WGS84 控制点对）为当前生效标定。

    服务端重新做最小二乘拟合（不信客户端算的参数），返回拟合统计 +
    逆变换系数（客户端地图点击→本地坐标用）。历史行保留，可重复保存。
    """
    from core.calibration import fit_calibration_transform
    from core.models import SiteCalibration
    from core.dxf_pipeline_utils import _bust_calibration_cache, active_calibration_info
    if not _pipeline_dxf_gate(request.user):
        return JsonResponse({'success': False, 'error': '无权限'}, status=403)
    pairs, err = _cal_pairs_from_post(request)
    if err:
        return JsonResponse({'success': False, 'error': err}, status=400)
    method = (request.POST.get('method') or '').strip()
    if method not in ('', 'sim', 'tps', 'mls'):
        return JsonResponse({'success': False, 'error': '未知的拟合方法'}, status=400)
    cal = [{'dxf_x': p['dxf_x'], 'dxf_y': -p['dxf_y'], 'lat': p['lat'], 'lng': p['lng']}
           for p in pairs]
    fn, stats = fit_calibration_transform(cal, method or None)
    if not callable(fn):
        return JsonResponse({'success': False, 'error': stats or '标定点退化'}, status=400)
    SiteCalibration.objects.create(
        points=pairs,
        method=method,
        note=(request.POST.get('note') or '').strip()[:200],
        created_by=request.user if request.user.is_authenticated else None,
    )
    _bust_calibration_cache()
    info = active_calibration_info()
    return JsonResponse({'success': True, 'calibration': info})


@require_POST
@login_required(login_url='core:login')
def pipeline_dxf_calibration_apply(request):
    """AJAX: 把新的生效标定追溯应用到已保存的管道/阀门坐标。

    已存数据是按「上一生效标定」换算的，所以重算 = old⁻¹ ∘ new：
    先把每个 lat/lng 还原回本地坐标，再按新标定正向变换。执行前把全部
    管道/阀门坐标备份为 JSON 文件。POST 需带 confirm=1。
    """
    import json as _json
    from django.db import transaction
    from django.utils import timezone as _tz
    from core.calibration import (SITE_CALIBRATION_POINTS,
                                fit_calibration_transform, fit_calibration_inverse)
    from core.models import SiteCalibration, Pipeline, PipeValve, PipelineImportBatch
    from core.dxf_pipeline_utils import _bust_calibration_cache
    if not _pipeline_dxf_gate(request.user):
        return JsonResponse({'success': False, 'error': '无权限'}, status=403)
    if request.POST.get('confirm') != '1':
        return JsonResponse({'success': False, 'error': '缺少确认参数'}, status=400)

    rows = list(SiteCalibration.objects.order_by('-id')[:20])
    if not rows:
        return JsonResponse({'success': False, 'error': '还没有已保存的用户标定'}, status=400)
    new_row = rows[0]
    if new_row.applied_at:
        # 幂等保护：库中坐标已按该标定重算过，再叠加一次会重复移动
        return JsonResponse({'success': False,
                             'error': '当前标定已应用过（%s）。如需再次重算，请先保存一份新标定。'
                                      % new_row.applied_at.strftime('%m-%d %H:%M')}, status=400)
    # old（逐批次推导）：某批管道的当前坐标活在哪个标定下 =
    #   max(该批导入时刻的生效标定, 最近一次 applied 的行)，按行序(id)。
    # 旧实现把全库当作活在同一个 old 下（最近 applied 行 / 默认两点）——在
    # 「新标定已保存但未应用」窗口里导入的批次实际活在导入时标定下，用错误
    # 的 old⁻¹ 还原，每保存+应用一轮就叠加一次偏差（表现为"导入的线条越调
    # 越歪"）。导入时标定 = created_at ≤ 批次 imported_at 的最新行（auto_now_add
    # 单调，id 序即时间序）；该时刻无行则硬编码默认两点。手动建的管道无批次，
    # 沿用旧语义（最近 applied 行 / 默认两点）。
    new_pts = new_row.points
    new_method = new_row.method or ''
    if not new_pts or len(new_pts) < 2:
        return JsonResponse({'success': False, 'error': '新标定点数不足'}, status=400)

    hist = list(SiteCalibration.objects.order_by('id')
                .values('id', 'created_at', 'points', 'method', 'applied_at'))
    rows_by_id = {r['id']: r for r in hist}
    last_applied = max((r for r in hist if r['applied_at']),
                       key=lambda r: r['id'], default=None)
    DEFAULT_OLD = {'id': 0, 'points': SITE_CALIBRATION_POINTS, 'method': ''}
    # 闸门/无批次管道对照用的全局 old：最近 applied 行，无则默认两点
    gate_old = last_applied or DEFAULT_OLD

    def old_row_of(imported_at):
        row = DEFAULT_OLD
        for r in hist:
            if r['created_at'] <= imported_at:
                row = r
        if last_applied and last_applied['id'] > row['id']:
            return last_applied   # 批次导入后有过 apply：全库已搬到该行
        return row

    def _fit_row(row):
        """→ (fn, stats, inv)。inv 为该标定的反向变换，退化时 None。"""
        cal = [{'dxf_x': float(p['dxf_x']), 'dxf_y': -float(p['dxf_y']),
                'lat': float(p['lat']), 'lng': float(p['lng'])} for p in row['points']]
        fn, stats = fit_calibration_transform(cal, row['method'] or None)
        inv = fit_calibration_inverse(cal, row['method'] or '') if callable(fn) else None
        return fn, stats, inv

    new_fn, new_stats, _ni = _fit_row({'id': new_row.id, 'created_at': None,
                                       'points': new_pts, 'method': new_method,
                                       'applied_at': None})
    if not callable(new_fn):
        return JsonResponse({'success': False, 'error': '新标定拟合失败'}, status=400)
    _gf, gate_stats, _gi = _fit_row(gate_old)
    if not callable(_gf):
        return JsonResponse({'success': False, 'error': '上一标定拟合失败'}, status=400)

    from core.pipe_utils import _to_latlng

    _inv_cache = {}   # 标定行 id → 反向变换（同一行的多条管道只拟一次）
    def old_inv_of(row):
        if row['id'] not in _inv_cache:
            _inv_cache[row['id']] = _fit_row(row)[2]
        return _inv_cache[row['id']]

    def _remap_pt(inv, pt):
        # 兼容 dict {lat,lng} 与历史数组 [lat,lng] 两种行格式；输出统一 dict。
        ll = _to_latlng(pt)
        if ll is None:
            return pt   # 无法解析的行原样保留（不因个别脏数据中断整批重算）
        x, y = inv(ll[0], ll[1])
        la, ln = new_fn(x, y)
        return {'lat': round(float(la), 7), 'lng': round(float(ln), 7)}

    # 注：此前带「整体微调」偏移导入的批次，其偏移会随组合变换近似映射，
    # 不做逐批偏移簿记（偏差在亚米级，记录成本不值）。
    # 安全闸的比例/旋转取相似变换对照值（TPS stats 里同样带，退化时为 None
    # → 视作 0，不拦）。TPS 的"比例"本身只是参考量级。
    drift = ((new_stats['scale'] / gate_stats['scale']) - 1) * 100 if gate_stats['scale'] else 0
    rot_change = (new_stats['rotation_deg'] or 0) - (gate_stats['rotation_deg'] or 0)
    rot_change = ((rot_change + 180.0) % 360.0) - 180.0   # ±180° 环绕归一
    # 安全闸：比例/旋转剧变几乎总是选点错误（正常土建/卫星偏差在个位数百分比和
    # 小角度内）。需显式 force=1 才放行，防止误操作大规模移动已存坐标。
    if request.POST.get('force') != '1' and (abs(drift) > 15 or abs(rot_change) > 10):
        return JsonResponse({
            'success': False, 'need_force': True,
            'error': f'新旧标定差异过大（比例 {drift:+.1f}%，旋转 {rot_change:+.1f}°），'
                     '通常是标定点选错。请核对三组点；确认无误请再点一次确认强制应用。',
            'scale_change_pct': round(drift, 3),
            'rotation_change_deg': round(rot_change, 3),
        }, status=400)

    # 备份：全部现有坐标写入时间戳 JSON（回滚用）。uuid 后缀防同秒覆盖。
    import os
    import uuid as _uuid
    from django.conf import settings as _settings
    try:
        backup_dir = os.path.join(_settings.BASE_DIR, 'pipeline_backups')
        os.makedirs(backup_dir, exist_ok=True)
        ts = _tz.localtime().strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(backup_dir, f'recalib_{ts}_{_uuid.uuid4().hex[:6]}.json')
        with open(backup_path, 'w', encoding='utf-8') as bf:
            _json.dump({
                'created_at': _tz.now().isoformat(),
                # 逐批旧标定（重算依据）：id → {points, method}；历史行可按 id
                # 从 SiteCalibration 复原。gate_old 仅为闸门对照，不参与重算。
                'old_calibration': gate_old['points'], 'new_calibration': new_pts,
                'old_calibration_rows': {str(r['id']): {'points': r['points'],
                                                        'method': r['method']}
                                         for r in hist},
                'pipelines': [{'id': p.id, 'line_points': p.line_points}
                              for p in Pipeline.objects.all().only('id', 'line_points')],
                'valves': [{'id': v.id, 'point': v.point}
                           for v in PipeValve.objects.all().only('id', 'point')],
            }, bf, ensure_ascii=False)
    except OSError as exc:
        return JsonResponse({'success': False,
                             'error': f'备份文件写入失败，已中止（{exc.__class__.__name__}）'}, status=500)

    n_pipes = n_valves = 0
    with transaction.atomic():
        # 快照在事务内取，缩小与并发编辑的竞态窗口。按「旧标定行」分组管道，
        # 每组用各自的 old⁻¹∘new 重算——不同批次可以活在不同的标定下。
        batch_ts = dict(PipelineImportBatch.objects.values_list('id', 'imported_at'))
        old_key_by_pid = {}
        groups = {}   # 旧标定行 id → [pipelines]
        for p in Pipeline.objects.all().only('id', 'line_points', 'import_batch_id'):
            ts = batch_ts.get(p.import_batch_id)
            key = old_row_of(ts)['id'] if ts else gate_old['id']
            old_key_by_pid[p.id] = key
            groups.setdefault(key, []).append(p)
        # 写入前统一解析全部需要的逆变换——有任何不可逆就在零写入时退出
        # （atomic 块正常退出即 commit，中途 return 会把已 save 的部分提交）。
        for key in sorted(set(groups) | {gate_old['id']}):
            row = DEFAULT_OLD if key == 0 else rows_by_id[key]
            if old_inv_of(row) is None:
                return JsonResponse({'success': False,
                                     'error': f'标定 #{key} 不可逆，已中止（未改动任何数据）'},
                                    status=400)
        for key, plist in groups.items():
            inv = _inv_cache[key]
            for p in plist:
                if not p.line_points:
                    continue
                p.line_points = [_remap_pt(inv, pt) for pt in p.line_points]
                p.save(update_fields=['line_points'])
                n_pipes += 1
        for v in PipeValve.objects.all().only('id', 'point', 'pipeline_id').iterator():
            if not v.point:
                continue
            key = old_key_by_pid.get(v.pipeline_id, gate_old['id'])
            inv = _inv_cache[key]
            v.point = [_remap_pt(inv, v.point[0])]
            v.save(update_fields=['point'])
            n_valves += 1
        SiteCalibration.objects.filter(pk=new_row.pk).update(applied_at=_tz.now())
    _invalidate_cached('dashboard:pipelines')
    _bust_calibration_cache()

    # 事后核验：应用后每个控制点的卫星位置距最近管线顶点应≈0。>0.5m
    # 说明这一轮换算有残差（逆推近似的累积），提示用户但不算失败——
    # 再保存应用一轮或喊管理员重锚定即可收敛。
    import math as _math
    verts = []
    for p in Pipeline.objects.all().only('line_points').iterator():
        for pt in (p.line_points or []):
            ll = _to_latlng(pt)
            if ll:
                verts.append(ll)
    ctrl_max = 0.0
    if verts:
        for cp in new_pts:
            la, ln = float(cp['lat']), float(cp['lng'])
            d = min(_math.hypot((v[0] - la) * 111320.0,
                                (v[1] - ln) * 111320.0 * _math.cos(_math.radians(la)))
                    for v in verts)
            ctrl_max = max(ctrl_max, d)
    return JsonResponse({
        'success': True,
        'pipelines': n_pipes, 'valves': n_valves,
        'scale_change_pct': round(drift, 3),
        'rotation_change_deg': round(rot_change, 3),
        'backup': os.path.basename(backup_path),
        'ctrl_max_m': round(ctrl_max, 3),
    })


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
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({'success': False, 'error': '映射参数格式无效'}, status=400)
    if not layer_specs:
        return JsonResponse({'success': False, 'error': '请至少选择一个管道图层'}, status=400)
    # 整体微调偏移（度）：预览阶段用户拖动校准的结果，导入时叠加到最终坐标
    try:
        offset = (float(request.POST.get('offset_lat') or 0),
                  float(request.POST.get('offset_lng') or 0))
    except (TypeError, ValueError):
        offset = (0.0, 0.0)
    try:
        result = import_dxf_pipelines(
            layer_specs, block_specs, uploaded_file=f,
            label_layers=label_layers, offset=offset, token=token,
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
    from .models import Pipeline, PipeValve, Zone
    if not _pipeline_dxf_gate(request.user):
        return JsonResponse({'success': False, 'error': '无权限'}, status=403)
    pipes = []
    for p in (Pipeline.objects.all().order_by('id')):
        pipes.append({
            'id': p.id, 'name': p.name, 'code': p.code,
            'type': p.pipeline_type, 'type_display': p.get_pipeline_type_display(),
            'diameter': p.main_diameter, 'color': p.line_color,
            'line_points': p.line_points, 'source': p.source_label or '',
        })
    valves = []
    for v in (PipeValve.objects.select_related('zone', 'station').order_by('id')):
        valves.append({
            'id': v.id, 'pipeline_id': v.pipeline_id,
            'name': v.name or '', 'type': v.valve_type,
            'type_display': v.get_valve_type_display(),
            'diameter': v.diameter, 'point': v.point,
            'zone_id': v.zone_id, 'zone_label': (v.zone.code + ' ' + v.zone.name) if v.zone else '',
            'station_id': v.station_id,
        })
    zones = [{'id': z.id, 'label': f'{z.code} {z.name}'}
             for z in Zone.objects.order_by('code')]
    return JsonResponse({'success': True, 'pipelines': pipes,
                         'valves': valves, 'zones': zones})


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
