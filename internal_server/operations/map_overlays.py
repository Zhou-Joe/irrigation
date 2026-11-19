"""HD imagery overlays pinned onto the team map by three draggable corner anchors."""
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST
from PIL import Image

from .access import require_member, audit
from .models import MapImageOverlay

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
ALLOWED_TYPES = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp'}


def _payload(item):
    anchors = None
    if item.calibrated:
        anchors = {'tl': [item.tl_lat, item.tl_lng], 'tr': [item.tr_lat, item.tr_lng],
                   'bl': [item.bl_lat, item.bl_lng]}
    return {'id': item.pk, 'name': item.name, 'image_url': f'/ops/map-overlays/{item.pk}/image/',
            'width': item.width, 'height': item.height, 'opacity': item.opacity,
            'active': item.active, 'calibrated': item.calibrated, 'anchors': anchors}


def _parse_anchors(request):
    values = {}
    for key in ('tl_lat', 'tl_lng', 'tr_lat', 'tr_lng', 'bl_lat', 'bl_lng'):
        raw = request.POST.get(key, '')
        try:
            values[key] = float(raw)
        except (TypeError, ValueError):
            raise ValueError('角点坐标必须是数字。')
    for key in ('tl_lat', 'tr_lat', 'bl_lat'):
        if not -90 <= values[key] <= 90:
            raise ValueError('纬度超出范围。')
    for key in ('tl_lng', 'tr_lng', 'bl_lng'):
        if not -180 <= values[key] <= 180:
            raise ValueError('经度超出范围。')
    tl = (values['tl_lat'], values['tl_lng'])
    tr = (values['tr_lat'], values['tr_lng'])
    bl = (values['bl_lat'], values['bl_lng'])
    if tl == tr or tl == bl:
        raise ValueError('三个角点不能重合，请在地图上拖开后再保存。')
    return values


@login_required
@require_GET
def image(request, pk):
    """Serve overlay rasters behind login; /media/* stays blocked for pest members."""
    require_member(request)
    item = get_object_or_404(MapImageOverlay, pk=pk)
    path = Path(item.image.path)
    if not path.is_file():
        raise Http404
    response = FileResponse(path.open('rb'), content_type='image/png' if path.suffix == '.png'
                            else 'image/webp' if path.suffix == '.webp' else 'image/jpeg')
    response['Cache-Control'] = 'private, max-age=86400'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@login_required
@require_GET
def collection(request):
    """Every member can view overlays; calibration and upload stay manager-only."""
    require_member(request)
    items = MapImageOverlay.objects.order_by('pk')
    return JsonResponse({'success': True, 'overlays': [_payload(item) for item in items]})


@login_required
@require_POST
def upload(request):
    member = require_member(request, manager=True)
    name = request.POST.get('name', '').strip()[:100] or '未命名影像'
    upload_file = request.FILES.get('image')
    if upload_file is None:
        return JsonResponse({'success': False, 'message': '请选择影像文件。'}, status=400)
    if upload_file.size > MAX_UPLOAD_BYTES:
        return JsonResponse({'success': False, 'message': '影像不能超过 15 MB。'}, status=400)
    suffix = ALLOWED_TYPES.get(upload_file.content_type)
    if suffix is None:
        return JsonResponse({'success': False, 'message': '仅支持 JPG、PNG 或 WebP 影像。'}, status=400)
    item = MapImageOverlay(name=name, created_by=request.user)
    item.image.save(upload_file.name, upload_file, save=False)
    try:
        with Image.open(item.image) as probe:
            probe.verify()
        with Image.open(item.image) as probe:
            item.width, item.height = probe.size
    except Exception:
        item.image.delete(save=False)
        return JsonResponse({'success': False, 'message': '文件不是有效的图片，请检查后重试。'}, status=400)
    with transaction.atomic():
        item.save()
        audit(request, member.team, 'overlay.upload', item.pk, name=name)
    return JsonResponse({'success': True, 'message': '影像已上传，请在地图上校准位置。', 'overlay': _payload(item)})


@login_required
@require_POST
def calibrate(request, pk):
    member = require_member(request, manager=True)
    item = get_object_or_404(MapImageOverlay, pk=pk)
    try:
        anchors = _parse_anchors(request)
    except ValueError as exc:
        return JsonResponse({'success': False, 'message': str(exc)}, status=400)
    for key, value in anchors.items():
        setattr(item, key, value)
    item.save(update_fields=list(anchors))
    item.refresh_from_db()
    audit(request, member.team, 'overlay.calibrate', item.pk, name=item.name)
    return JsonResponse({'success': True, 'message': '校准已保存。', 'overlay': _payload(item)})


@login_required
@require_POST
def update(request, pk):
    member = require_member(request, manager=True)
    item = get_object_or_404(MapImageOverlay, pk=pk)
    fields = []
    if 'name' in request.POST:
        name = request.POST.get('name', '').strip()[:100]
        if not name:
            return JsonResponse({'success': False, 'message': '名称不能为空。'}, status=400)
        item.name = name
        fields.append('name')
    if 'opacity' in request.POST:
        try:
            opacity = float(request.POST['opacity'])
        except (TypeError, ValueError):
            return JsonResponse({'success': False, 'message': '透明度必须是数字。'}, status=400)
        if not 0.1 <= opacity <= 1:
            return JsonResponse({'success': False, 'message': '透明度范围 0.1–1。'}, status=400)
        item.opacity = opacity
        fields.append('opacity')
    if 'active' in request.POST:
        item.active = request.POST['active'] in ('true', '1', 'True')
        fields.append('active')
    if not fields:
        return JsonResponse({'success': False, 'message': '没有需要更新的内容。'}, status=400)
    item.save(update_fields=fields)
    return JsonResponse({'success': True, 'message': '已更新。', 'overlay': _payload(item)})


@login_required
@require_POST
def remove(request, pk):
    member = require_member(request, manager=True)
    item = get_object_or_404(MapImageOverlay, pk=pk)
    name = item.name
    with transaction.atomic():
        item.delete()
        audit(request, member.team, 'overlay.delete', pk, name=name)
    item.image.delete(save=False)
    return JsonResponse({'success': True, 'message': f'已删除「{name}」。'})
