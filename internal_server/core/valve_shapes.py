"""Shared map glyphs, edited by the same roles as the pipeline editor."""
import json
from django.contrib.auth.decorators import login_required
from django.db.models import F
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from .dxf_views import _pipeline_dxf_gate
from .models import PipeValve, ValveMapShape


def library():
    return {row.valve_type: {'paths': row.paths, 'offset': row.offset, 'revision': row.revision}
            for row in ValveMapShape.objects.all()}


def clean_shape(data):
    if not isinstance(data, dict) or data.get('type') not in dict(PipeValve.VALVE_TYPE_CHOICES):
        raise ValueError('请选择有效阀型。')
    paths, offset, revision = (data.get(k) for k in ('paths', 'offset', 'revision'))
    if type(revision) is not int or revision < 0:
        raise ValueError('版本无效，请重新打开页面。')
    if type(offset) is not int or not -180 <= offset <= 180:
        raise ValueError('角度补偿须为 −180 到 180 度的整数。')
    if not isinstance(paths, list) or len(paths) > 32:
        raise ValueError('每个图案最多可画 32 笔。')
    for path in paths:
        if not isinstance(path, list) or not 2 <= len(path) <= 256:
            raise ValueError('每笔应包含 2 到 256 个点。')
        for point in path:
            if not isinstance(point, list) or len(point) != 2 or any(type(n) is not int or not 0 <= n <= 64 for n in point):
                raise ValueError('图案坐标无效。')
        if all(p == path[0] for p in path):
            raise ValueError('笔画需要至少两个不同的点。')
    return data['type'], paths, offset, revision


@login_required
@require_http_methods(['GET', 'POST'])
@ensure_csrf_cookie
def editor(request):
    if not _pipeline_dxf_gate(request.user):
        return JsonResponse({'error': '无管道管理权限。'}, status=403)
    if request.method == 'GET':
        return render(request, 'core/valve_shapes.html', {'valve_types': PipeValve.VALVE_TYPE_CHOICES, 'shapes': library()})
    try:
        kind, paths, offset, revision = clean_shape(json.loads(request.body))
    except (TypeError, json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': '图案格式无效。'}, status=400)
    except ValueError as error:
        return JsonResponse({'error': str(error)}, status=400)
    ValveMapShape.objects.get_or_create(valve_type=kind)
    updated = ValveMapShape.objects.filter(valve_type=kind, revision=revision).update(
        paths=paths, offset=offset if paths else 0, revision=F('revision') + 1)
    if not updated:
        return JsonResponse({'error': '此阀型刚被其他人修改，请刷新后核对。'}, status=409)
    return JsonResponse({'success': True, 'revision': revision + 1})
