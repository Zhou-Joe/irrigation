"""Versioned calibration and signed preview state for CAD imports."""
import math
from copy import deepcopy

from django.conf import settings
from django.core import signing

from .calibration import SITE_CALIBRATION_POINTS, fit_calibration_transform

PREVIEW_SALT = 'core.pipeline-dxf-preview.v1'
PREVIEW_MAX_AGE = 15 * 60


def calibration_snapshot(drawing_token=None, calibration_id=None):
    from .models import SiteCalibration
    rows = SiteCalibration.objects.all()
    if calibration_id is not None:
        row = rows.filter(pk=calibration_id).first()
        if row is None:
            raise ValueError('标定记录不存在，请刷新预览')
        if drawing_token and row.drawing_token and row.drawing_token != drawing_token:
            raise ValueError('标定与当前图纸不一致，请重新校准')
    else:
        scoped = rows.filter(drawing_token=drawing_token).order_by('-id').first() if drawing_token else None
        if scoped:
            row = scoped if scoped.is_active else None
        else:
            row = rows.filter(is_active=True, drawing_token='').order_by('-id').first()
    if row:
        return {'id': row.pk, 'points': deepcopy(row.points),
                'method': row.method, 'drawing_token': row.drawing_token,
                'check_points': deepcopy(row.check_points)}
    return {'id': 0, 'points': deepcopy(SITE_CALIBRATION_POINTS),
            'method': 'sim', 'drawing_token': drawing_token or ''}


def fit_snapshot(snapshot):
    pairs = [{'dxf_x': float(p['dxf_x']), 'dxf_y': -float(p['dxf_y']),
              'lat': float(p['lat']), 'lng': float(p['lng'])}
             for p in snapshot['points']]
    return fit_calibration_transform(pairs, snapshot.get('method') or None)


def calibration_quality(snapshot):
    limit = float(getattr(settings, 'DXF_CALIBRATION_MAX_RMS_M', 5.0))
    try:
        if snapshot.get('method') == 'tps' and len(snapshot['points']) < 4:
            raise ValueError('TPS 至少需要 4 个标定点')
        fn, stats = fit_snapshot(snapshot)
        if not callable(fn):
            return {'valid': False, 'error': str(stats), 'limit_m': limit}
        scale = stats.get('scale')
        if scale is None or not math.isfinite(scale) or scale <= 1e-12:
            raise ValueError('标定比例退化，请检查对应点')
        for p in snapshot['points']:
            la, ln = fn(p['dxf_x'], -p['dxf_y'])
            if not (math.isfinite(la) and math.isfinite(ln)
                    and -90 <= la <= 90 and -180 <= ln <= 180):
                raise ValueError('标定结果包含无效坐标')
        rms = stats.get('rms_m')
        if rms is None and len(snapshot['points']) > 2:
            raise ValueError('无法验证标定误差，请减少点数或检查点的分布')
        if rms is not None and (not math.isfinite(rms) or rms > limit):
            raise ValueError(f'标定验证误差 {rms:.2f} m 超过 {limit:g} m，请删除选错的点并重新校准')
        return {'valid': True, 'rms_m': rms, 'limit_m': limit}
    except (ValueError, TypeError, KeyError, ZeroDivisionError, OverflowError) as exc:
        return {'valid': False, 'error': str(exc), 'limit_m': limit}


def require_quality(snapshot):
    quality = calibration_quality(snapshot)
    if not quality['valid']:
        raise ValueError(quality['error'])


def alignment_status(snapshot):
    """Eligibility for new positioning: one shape-preserving fit, independently checked."""
    limit = float(getattr(settings, 'DXF_CALIBRATION_MAX_RMS_M', 5.0))
    result = {'ready': False, 'limit_m': limit, 'control_count': len(snapshot.get('points', [])),
              'check_count': len(snapshot.get('check_points', []))}
    try:
        if snapshot.get('method') != 'sim':
            raise ValueError('旧变形标定仅供历史显示，请使用控制点重新对齐')
        controls = snapshot.get('points', [])
        checks = snapshot.get('check_points', [])
        if len(controls) < 3:
            raise ValueError('请添加至少 3 个分布在图纸不同区域的对齐点')
        # A nearly straight control layout cannot validate position across a drawing.
        xs, ys = [float(p['dxf_x']) for p in controls], [float(p['dxf_y']) for p in controls]
        mx, my = sum(xs)/len(xs), sum(ys)/len(ys)
        xx, yy = sum((x-mx)**2 for x in xs), sum((y-my)**2 for y in ys)
        xy = sum((x-mx)*(y-my) for x,y in zip(xs,ys))
        if not math.isfinite(xx+yy) or xx+yy <= 1e-12 or (xx*yy-xy*xy)/(xx+yy)**2 < 1e-4:
            raise ValueError('对齐点重复或接近一条直线，请选取覆盖不同方向的点')
        separation = max(math.sqrt((xx+yy)/len(xs))*1e-6, 1e-9)
        if any(math.hypot(xs[i]-xs[j], ys[i]-ys[j]) <= separation
               for i in range(len(xs)) for j in range(i)):
            raise ValueError('对齐点不能重复，请选取不同的 CAD 点')
        require_quality(snapshot)
        fn, stats = fit_snapshot(snapshot)
        control_errors = []
        for point in controls:
            la, ln = fn(point['dxf_x'], -point['dxf_y'])
            control_errors.append(math.hypot(
                (la-point['lat'])*111320,
                (ln-point['lng'])*111320*math.cos(math.radians(point['lat']))))
        if max(control_errors, default=0) > limit:
            raise ValueError(f'对齐点最大误差超过 {limit:g} m，请重选误差较大的点')
        if not checks:
            raise ValueError('请添加至少 1 个独立检查点；检查点不参与拟合')
        errors = []
        seen_checks = []
        for point in checks:
            x, y, la, ln = (float(point[k]) for k in ('dxf_x','dxf_y','lat','lng'))
            if not all(math.isfinite(v) for v in (x,y,la,ln)) or not (-90 <= la <= 90 and -180 <= ln <= 180):
                raise ValueError('检查点坐标无效')
            if any(math.hypot(x-cx, y-cy) <= separation for cx,cy in zip(xs,ys)):
                raise ValueError('检查点必须与对齐点不同，不能复用同一个 CAD 点')
            if any(math.hypot(x-cx, y-cy) <= separation for cx,cy in seen_checks):
                raise ValueError('检查点不能重复，请选取不同的 CAD 点')
            seen_checks.append((x, y))
            pla, pln = fn(x, -y)
            if not (math.isfinite(pla) and math.isfinite(pln)
                    and -90 <= pla <= 90 and -180 <= pln <= 180):
                raise ValueError('检查点超出有效地图坐标范围')
            errors.append(math.hypot((pla-la)*111320, (pln-ln)*111320*math.cos(math.radians(la))))
        result.update(rms_m=stats['rms_m'], check_errors_m=errors, check_max_m=max(errors))
        if not all(math.isfinite(e) for e in errors) or max(errors) > limit:
            raise ValueError(f'独立检查点误差 {max(errors):.2f} m 超过 {limit:g} m，请核对对应位置')
        result['ready'] = True
    except (ValueError, TypeError, KeyError, ZeroDivisionError, OverflowError) as exc:
        result['error'] = str(exc)
    return result


def require_alignment(snapshot):
    status = alignment_status(snapshot)
    if not status['ready']:
        raise ValueError(status['error'])


def sign_preview(token, snapshot, user_id=None):
    return signing.dumps({'token': token, 'calibration': snapshot, 'user_id': user_id},
                         salt=PREVIEW_SALT, compress=True)


def read_preview(preview_token, token=None, user_id=None):
    try:
        state = signing.loads(preview_token, salt=PREVIEW_SALT, max_age=PREVIEW_MAX_AGE)
    except signing.BadSignature as exc:
        raise ValueError('预览已过期或无效，请重新解析图纸') from exc
    if token and state['token'] != token:
        raise ValueError('文件与预览不一致，请重新解析图纸')
    if state.get('user_id') is not None and state['user_id'] != user_id:
        raise ValueError('预览不属于当前用户，请重新解析图纸')
    return state


def same_transform(a, b):
    return a.get('points') == b.get('points') and a.get('method', '') == b.get('method', '')
