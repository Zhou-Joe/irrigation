"""Reproject imported CAD batches from source coordinates, preserving corrections."""
import json
import math
import uuid
from copy import deepcopy
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .calibration import SITE_CALIBRATION_POINTS, fit_calibration_inverse
from .dxf_state import calibration_snapshot, fit_snapshot, require_quality, same_transform
from .models import Pipeline, PipelineImportBatch, PipeValve, SiteCalibration
from .pipe_utils import _to_latlng


def _legacy_snapshot(batch, history):
    rows = [r for r in history if not r.drawing_token or r.drawing_token == batch.source_token]
    at_import = next((r for r in reversed(rows) if r.created_at <= batch.imported_at), None)
    applied = next((r for r in reversed(rows) if r.applied_at), None)
    row = max([r for r in (at_import, applied) if r], key=lambda r: r.pk, default=None)
    if row:
        return calibration_snapshot(calibration_id=row.pk)
    return {'id': 0, 'points': deepcopy(SITE_CALIBRATION_POINTS),
        'method': 'sim', 'drawing_token': ''}


def _source_from_legacy(points, snapshot):
    fn, stats = fit_snapshot(snapshot)
    if not callable(fn):
        raise ValueError('旧标定不可逆，未修改任何坐标')
    if stats.get('method') in ('tps', 'mls'):
        raise ValueError('旧批次缺少原始 CAD 坐标，非线性标定不可逆；请重新导入原图')
    pairs = [dict(p, dxf_y=-p['dxf_y']) for p in snapshot['points']]
    inv = fit_calibration_inverse(pairs, 'sim')
    if inv is None:
        raise ValueError('旧标定不可逆，未修改任何坐标')
    source = []
    for point in points:
        ll = _to_latlng(point)
        if ll is None:
            raise ValueError('旧批次包含无效坐标，请先修复')
        x, y = inv(*ll)
        source.append([float(x), -float(y)])
    return source


def _derive(source, fn, offset, current, baseline):
    """Carry each explicitly edited vertex's map-space correction forward."""
    if len(source) != len(current) or (baseline and len(baseline) != len(source)):
        return None
    result, derived = [], []
    baseline = baseline or current
    for (x, y), now, old in zip(source, current, baseline):
        la, ln = fn(x, -y)
        raw = {'lat': round(float(la) + offset[0], 7),
               'lng': round(float(ln) + offset[1], 7)}
        now_ll, old_ll = _to_latlng(now), _to_latlng(old)
        if now_ll is None or old_ll is None:
            raise ValueError('管道或阀门包含无效坐标')
        adjusted = {'lat': round(raw['lat'] + now_ll[0] - old_ll[0], 7),
                    'lng': round(raw['lng'] + now_ll[1] - old_ll[1], 7)}
        for point in (raw, adjusted):
            if not (math.isfinite(point['lat']) and math.isfinite(point['lng'])
                    and -90 <= point['lat'] <= 90 and -180 <= point['lng'] <= 180):
                raise ValueError('新标定在管网范围内产生无效坐标，请重新校准')
        derived.append(raw)
        result.append(adjusted)
    return result, derived


def apply_calibration(calibration_id=None, batch_ids=None, force=False, discard_legacy_offset=False):
    from .dxf_pipeline_utils import _load_zone_data, _crossed_zone_ids
    snapshot = calibration_snapshot(calibration_id=calibration_id)
    if not snapshot['id']:
        raise ValueError('还没有已保存的用户标定')
    require_quality(snapshot)
    fn, new_stats = fit_snapshot(snapshot)
    history = list(SiteCalibration.objects.order_by('id'))
    zone_rings, _ = _load_zone_data()
    n_pipes = n_valves = unchanged = 0
    backup_path = None
    with transaction.atomic():
        batches = PipelineImportBatch.objects.select_for_update().order_by('id')
        if batch_ids is not None:
            batches = batches.filter(pk__in=batch_ids)
            if batches.count() != len(set(batch_ids)):
                raise ValueError('所选导入批次不存在')
        elif snapshot.get('drawing_token'):
            batches = batches.filter(source_token=snapshot['drawing_token'])
        plans, batch_plans = [], []
        max_drift = max_rotation = 0.0
        for batch in batches:
            if snapshot.get('drawing_token') and snapshot['drawing_token'] != batch.source_token:
                raise ValueError('标定与所选批次的图纸不一致')
            old = batch.applied_calibration or batch.calibration_snapshot or _legacy_snapshot(batch, history)
            old_offset = batch.import_options.get('offset', [0, 0])
            remove_offset = discard_legacy_offset and any(old_offset)
            if same_transform(old, snapshot) and not remove_offset:
                unchanged += batch.pipelines.count()
                batch_plans.append((batch, old))
                continue
            old_fn, old_stats = fit_snapshot(old)
            if not callable(old_fn):
                raise ValueError('旧标定不可逆，未修改任何坐标')
            drift = ((new_stats['scale'] / old_stats['scale']) - 1) * 100 if old_stats['scale'] else 0
            rotation = ((new_stats['rotation_deg'] - old_stats['rotation_deg'] + 180) % 360) - 180
            max_drift = max(max_drift, abs(drift))
            max_rotation = max(max_rotation, abs(rotation))
            if not force and (abs(drift) > 15 or abs(rotation) > 10):
                return {'success': False, 'need_force': True,
                        'error': f'新旧标定差异过大（比例 {drift:+.1f}%，旋转 {rotation:+.1f}°），请核对对应点',
                        'scale_change_pct': round(drift, 3), 'rotation_change_deg': round(rotation, 3)}
            offset = [0, 0] if discard_legacy_offset else old_offset
            for pipe in batch.pipelines.select_for_update().order_by('id'):
                source = pipe.source_points or _source_from_legacy(pipe.line_points, old)
                derived = _derive(source, fn, offset, pipe.line_points, pipe.source_map_points)
                if derived is None:
                    raise ValueError(f'管道 {pipe.code} 已人工增删顶点，请先核对其 CAD 来源；未修改任何坐标')
                valve_plans = []
                for valve in pipe.valves.select_for_update().order_by('id'):
                    vsource = [valve.source_point] if valve.source_point else _source_from_legacy(valve.point, old)
                    vd = _derive(vsource, fn, offset, valve.point, valve.source_map_point)
                    if vd is None:
                        raise ValueError('阀门原始坐标与当前点数不一致，请先修复')
                    valve_plans.append((valve, vsource[0], vd))
                plans.append((pipe, source, derived, valve_plans))
            batch_plans.append((batch, old))

        # Validate the entire operation before creating the backup or writing rows.
        if plans:
            backup_dir = Path(settings.BASE_DIR) / 'pipeline_backups'
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = backup_dir / f'recalib_{timezone.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}.json'
            backup = {'created_at': timezone.now().isoformat(), 'new_calibration': snapshot,
                      'batches': [{'id': b.id, 'calibration_snapshot': b.calibration_snapshot,
                                   'applied_calibration': b.applied_calibration,
                                   'import_options': b.import_options} for b, _ in batch_plans],
                      'pipelines': [{'id': p.id, 'line_points': p.line_points,
                                     'source_points': p.source_points, 'source_map_points': p.source_map_points}
                                    for p, _, _, _ in plans],
                      'valves': [{'id': v.id, 'point': v.point, 'source_point': v.source_point,
                                  'source_map_point': v.source_map_point}
                                 for _, _, _, vs in plans for v, _, _ in vs]}
            with backup_path.open('w', encoding='utf-8') as stream:
                json.dump(backup, stream, ensure_ascii=False)
        for pipe, source, (points, baseline), valves in plans:
            pipe.source_points = source
            pipe.line_points, pipe.source_map_points = points, baseline
            pipe.save(update_fields=['source_points', 'line_points', 'source_map_points'])
            pipe.zones.set(_crossed_zone_ids([(p['lat'], p['lng']) for p in points], zone_rings))
            n_pipes += 1
            for valve, vsource, (points, baseline) in valves:
                valve.source_point = vsource
                valve.point, valve.source_map_point = points, baseline
                valve.save(update_fields=['source_point', 'point', 'source_map_point'])
                n_valves += 1
        for batch, old in batch_plans:
            if not batch.calibration_snapshot:
                batch.calibration_snapshot = old
            batch.applied_calibration = snapshot
            if discard_legacy_offset:
                batch.import_options = dict(batch.import_options, offset=[0, 0])
            batch.save(update_fields=['calibration_snapshot', 'applied_calibration', 'import_options'])
        SiteCalibration.objects.filter(pk=snapshot['id']).update(applied_at=timezone.now())
    return {'success': True, 'pipelines': n_pipes, 'valves': n_valves,
            'unchanged': unchanged,
            'skipped_manual': Pipeline.objects.filter(import_batch__isnull=True).count(),
            'scale_change_pct': round(max_drift, 3), 'rotation_change_deg': round(max_rotation, 3),
            'backup': backup_path.name if backup_path else ''}
