"""管道类型、样式及整批管理；写入前统一验证，删除前完整备份。"""
import json
import logging
import re
import uuid
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Pipeline, PipelineImportBatch, PipelineType

TYPE_DEFAULTS = [
    ('irrigation', '灌溉主管', '#CC3333'), ('flush', '冲洗主管', '#3366CC'),
    ('toilet', '冲厕主管', '#9B59B6'), ('casing', '过路套管', '#95A5A6'),
    ('control', '控制线', '#E67E22'), ('comm', '通讯线', '#1ABC9C'),
]
TYPE_CACHE = 'pipeline:type-options:v1'


def type_options() -> list[dict]:
    """六个内置类型与用户自定义类型共用同一份显示配置。"""
    options = cache.get(TYPE_CACHE)
    if options is None:
        values = {code: {'code': code, 'name': name, 'color': color} for code, name, color in TYPE_DEFAULTS}
        for row in PipelineType.objects.order_by('id').values('code', 'name', 'color'):
            values[row['code']] = row
        options = list(values.values())
        cache.set(TYPE_CACHE, options, 300)
    return options


def style_values(data, *, fallback_type='irrigation') -> dict:
    """只接受已登记类型、有效六位颜色及 1 至 10 像素线宽。"""
    result = {}
    if 'pipeline_type' in data:
        code = data.get('pipeline_type') or fallback_type
        if code not in {row['code'] for row in type_options()}:
            raise ValueError('请选择已登记的管道类型')
        result['pipeline_type'] = code
    if 'color' in data:
        color = str(data.get('color') or '').strip()
        if color and not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
            raise ValueError('管道颜色应为六位十六进制颜色')
        result['color'] = color.upper()
    if 'line_weight' in data:
        try:
            weight = int(data['line_weight'])
        except (ValueError, TypeError):
            raise ValueError('线宽必须为 1 至 10 的整数') from None
        if not 1 <= weight <= 10:
            raise ValueError('线宽必须为 1 至 10 的整数')
        result['line_weight'] = weight
        result['line_weight_custom'] = True
    return result


def _allowed(request):
    from .dxf_views import _pipeline_dxf_gate
    return _pipeline_dxf_gate(request.user)


@login_required(login_url='core:login')
@require_POST
def save_type(request):
    if not _allowed(request):
        return JsonResponse({'success': False, 'error': '无权限'}, status=403)
    name = (request.POST.get('name') or '').strip()
    code = (request.POST.get('code') or '').strip() or 'custom_' + uuid.uuid4().hex[:12]
    color = (request.POST.get('color') or '#2D6A4F').strip()
    if not name or len(name) > 80 or not re.fullmatch(r'[a-z][a-z0-9_]{0,19}', code):
        return JsonResponse({'success': False, 'error': '类型名称必填且最多80字；类型代码须为20位以内英文标识'}, status=400)
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
        return JsonResponse({'success': False, 'error': '颜色格式无效'}, status=400)
    if PipelineType.objects.filter(name=name).exclude(code=code).exists():
        return JsonResponse({'success': False, 'error': '类型名称已存在'}, status=400)
    PipelineType.objects.update_or_create(code=code, defaults={'name': name, 'color': color.upper()})
    cache.delete(TYPE_CACHE)
    from .views import _invalidate_cached
    _invalidate_cached('dashboard:pipelines')
    return JsonResponse({'success': True, 'types': type_options()})


@login_required(login_url='core:login')
@require_POST
def bulk_update(request):
    if not _allowed(request):
        return JsonResponse({'success': False, 'error': '无权限'}, status=403)
    try:
        changes = style_values(request.POST)
        if not changes:
            raise ValueError('请选择要修改的类型、颜色或线宽')
        ids = json.loads(request.POST.get('ids') or '[]')
        scope = request.POST.get('scope_type', '')
        if not isinstance(ids, list) or any(type(pk) is not int or pk <= 0 for pk in ids):
            raise ValueError('管道编号无效')
        if ids:
            queryset = Pipeline.objects.filter(pk__in=ids)
        elif scope and scope in {row['code'] for row in type_options()}:
            queryset = Pipeline.objects.filter(pipeline_type=scope)
        else:
            raise ValueError('请勾选管道或选择一个管道类型')
        with transaction.atomic():
            queryset = queryset.select_for_update()
            selected = list(queryset.values_list('pk', flat=True))
            if not selected or ids and len(selected) != len(set(ids)):
                raise ValueError('部分管道已删除，请刷新列表后重试')
            Pipeline.objects.filter(pk__in=selected).update(**changes, updated_at=timezone.now())
        from .views import _invalidate_cached
        _invalidate_cached('dashboard:pipelines')
        rows = Pipeline.objects.filter(pk__in=selected)
        return JsonResponse({'success': True, 'count': len(selected), 'pipelines': [
            {'id': row.pk, 'pipeline_type': row.pipeline_type, 'type_name': row.get_pipeline_type_display(),
             'color': row.line_color, 'color_override': row.color, 'line_weight': row.line_weight} for row in rows]})
    except (ValueError, TypeError) as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)


def delete_batch(request, batch_id):
    """备份成功后才删除；文件和数据库失败均返回明确的 JSON 错误。"""
    if not _allowed(request):
        return JsonResponse({'success': False, 'error': '无权限'}, status=403)
    try:
        with transaction.atomic():
            batch = PipelineImportBatch.objects.select_for_update().filter(pk=batch_id).first()
            if batch is None:
                return JsonResponse({'success': False, 'error': '批次不存在或已删除'}, status=404)
            pipes = list(batch.pipelines.select_for_update().prefetch_related('valves', 'zones'))
            # Include the original CAD, calibration and correction data needed for restoration.
            from django.forms.models import model_to_dict
            snapshot = {'version': 2, 'deleted_at': timezone.now(),
                        'batch': model_to_dict(batch), 'pipelines': []}
            snapshot['batch']['id'] = batch.pk
            snapshot['batch']['imported_at'] = batch.imported_at
            valve_count = 0
            for pipe in pipes:
                item = model_to_dict(pipe, exclude=['zones'])
                item['id'] = pipe.pk
                item['zone_ids'] = [zone.pk for zone in pipe.zones.all()]
                item['valves'] = [dict(model_to_dict(valve), id=valve.pk, zone_id=valve.zone_id, station_id=valve.station_id) for valve in pipe.valves.all()]
                valve_count += len(item['valves'])
                snapshot['pipelines'].append(item)
            backup_name = ''
            if pipes:
                folder = Path(getattr(settings, 'PIPELINE_BACKUP_ROOT', Path(settings.BASE_DIR) / 'pipeline_backups'))
                folder.mkdir(parents=True, exist_ok=True)
                backup_name = f'batchdel_{batch.pk}_{timezone.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}.json'
                encoded = json.dumps(snapshot, cls=DjangoJSONEncoder, ensure_ascii=False)
                with (folder / backup_name).open('x', encoding='utf-8') as stream:
                    stream.write(encoded)
                    stream.flush()
                    import os
                    os.fsync(stream.fileno())
            count = len(pipes)
            batch.pipelines.all().delete()
            batch.delete()
        from .views import _invalidate_cached
        try:
            _invalidate_cached('dashboard:pipelines')
        except Exception:
            logging.getLogger(__name__).exception('Pipeline cache refresh failed after deletion: %s', batch_id)
        return JsonResponse({'success': True, 'pipelines': count, 'valves': valve_count, 'backup': backup_name})
    except OSError:
        logging.getLogger(__name__).exception('Pipeline batch backup failed before deletion: %s', batch_id)
        return JsonResponse({'success': False, 'error': '坐标备份失败，未删除任何管道；请检查备份目录的写入权限和磁盘空间'}, status=500)
    except Exception:
        logging.getLogger(__name__).exception('Pipeline batch deletion rolled back: %s', batch_id)
        return JsonResponse({'success': False, 'error': '删除失败，数据库操作已回滚；请查看服务器日志'}, status=500)
