"""Private image/video attachments for team-scoped pest work orders."""
import mimetypes
import re
import uuid
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured
from django.http import FileResponse, Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_safe

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.m4v', '.webm'}
MAX_FILES = 10
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024
_NAME = re.compile(r'^[0-9a-f]{32}\.(?:jpg|jpeg|png|webp|gif|bmp|mp4|mov|m4v|webm)$')


def private_root():
    root = Path(getattr(settings, 'PEST_WORKORDER_PRIVATE_ROOT', settings.BASE_DIR / 'private_pest_workorders')).resolve()
    for public in (settings.MEDIA_ROOT, settings.STATIC_ROOT):
        if public and root.is_relative_to(Path(public).resolve()):
            raise ImproperlyConfigured('PEST_WORKORDER_PRIVATE_ROOT must be outside media/static directories')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def check_upload_limits(files, existing_count=0):
    if len(files) + existing_count > MAX_FILES:
        raise ValueError('每张工单最多保留 10 个图片或视频附件。')
    if any((getattr(file, 'size', 0) or 0) > MAX_FILE_BYTES for file in files):
        raise ValueError('单个附件不能超过 50 MB。')
    if sum(getattr(file, 'size', 0) or 0 for file in files) > MAX_TOTAL_BYTES:
        raise ValueError('本次上传的附件总大小不能超过 100 MB。')


def prepare_uploads(files, existing_count=0):
    """Validate every upload before any business/file write; return rewound streams."""
    files = list(files)
    check_upload_limits(files, existing_count)
    from core.upload_security import validate_upload
    for file in files:
        ext = Path(file.name).suffix.lower()
        if ext not in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
            raise ValueError('仅支持 JPG、PNG、WebP、GIF、BMP 图片及 MP4、MOV、M4V、WebM 视频。')
        valid, error = validate_upload(file)
        if not valid:
            raise ValueError(error)
        if ext in VIDEO_EXTENSIONS:
            file.seek(0)
            header = file.read(4096)
            if ext == '.webm':
                valid = header.startswith(b'\x1a\x45\xdf\xa3') and b'webm' in header
            else:
                valid = len(header) >= 12 and header[4:8] == b'ftyp'
                if ext == '.mov':
                    valid = valid or len(header) >= 8 and header[4:8] in (b'moov', b'mdat', b'wide')
            if not valid:
                raise ValueError('视频内容与格式不符或文件已损坏，请重新选择。')
        file.seek(0)
    return files


def _relative(reference):
    parts = str(reference).split('/')
    if len(parts) != 3 or parts[0] != 'pest_workorders' or not parts[1].isdigit() or not _NAME.fullmatch(parts[2]):
        return None
    return Path(parts[1]) / parts[2]


def delete_uploaded(references):
    for reference in references:
        relative = _relative(reference)
        if relative is not None:
            path = private_root() / relative
            path.unlink(missing_ok=True)
            try:
                path.parent.rmdir()
            except OSError:
                pass


def cleanup_unattached(request):
    """Discard files from a rolled-back request, preserving committed attachments."""
    from core.models import WorkReport
    saved = set(getattr(request, '_pest_created_media', []))
    if not saved:
        return
    stored = WorkReport.all_businesses.filter(pk=request._pest_media_report_id).values_list('photos', flat=True).first() or []
    delete_uploaded(saved - set(stored))


def save_uploaded(report, prepared):
    """Save validated streams, returning report.photos references; clean partial writes."""
    saved = []
    if not prepared:
        return saved
    folder = private_root() / str(report.pk)
    folder.mkdir(mode=0o700, exist_ok=True)
    try:
        for file in prepared:
            name = uuid.uuid4().hex + Path(file.name).suffix.lower()
            reference = f'pest_workorders/{report.pk}/{name}'
            saved.append(reference)
            with (folder / name).open('xb') as output:
                for chunk in file.chunks():
                    output.write(chunk)
            (folder / name).chmod(0o600)
        return saved
    except Exception:
        delete_uploaded(saved)
        raise


def media_items(report):
    items = []
    for reference in report.photos or []:
        relative = _relative(reference)
        if relative is None or relative.parts[0] != str(report.pk):
            continue
        video = relative.suffix in VIDEO_EXTENSIONS
        items.append({'reference': reference, 'video': video,
            'url': reverse('operations:workorder_media', kwargs={'report_id': report.pk, 'name': relative.name}),
            'label': ('视频' if video else '图片') + f' {len(items) + 1}'})
    return items


def _read_range(stream, remaining):
    try:
        while remaining:
            chunk = stream.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
    finally:
        stream.close()


def plan_submission(request, report):
    existing = list(report.photos or []) if report else []
    removed = set(request.POST.getlist('media_remove'))
    if not removed.issubset(existing):
        raise ValueError('待移除的附件不属于此工单，请刷新后重试。')
    kept = [reference for reference in existing if reference not in removed]
    return kept, removed, prepare_uploads(request.FILES.getlist('report_media'), len(kept))


def apply_submission(request, report, plan):
    from django.db import transaction
    kept, removed, prepared = plan
    saved = save_uploaded(report, prepared)
    request._pest_created_media = saved
    request._pest_media_report_id = report.pk
    report.photos = kept + saved
    report.save(update_fields=['photos'])
    if removed:
        # Cleanup failure after commit cannot turn a completed save into an
        # apparent failure or trigger rollback cleanup of the new attachments.
        transaction.on_commit(lambda: delete_uploaded(removed), robust=True)


@login_required
@require_safe
def serve(request, report_id, name):
    from .map_views import records
    if not _NAME.fullmatch(name):
        raise Http404
    report = get_object_or_404(records(request), pk=report_id)
    reference = f'pest_workorders/{report.pk}/{name}'
    if reference not in (report.photos or []):
        raise Http404
    path = private_root() / str(report.pk) / name
    try:
        stream = path.open('rb')
    except OSError:
        raise Http404 from None
    content_type = mimetypes.guess_type(name)[0] or 'application/octet-stream'
    size = path.stat().st_size
    raw_range = request.headers.get('Range')
    if raw_range:
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', raw_range)
        try:
            if not match or not any(match.groups()):
                raise ValueError
            first, last = match.groups()
            start = int(first) if first else max(0, size - int(last))
            end = min(size - 1, int(last)) if first and last else size - 1
            if not 0 <= start <= end < size:
                raise ValueError
        except (ValueError, OverflowError):
            stream.close()
            response = HttpResponse(status=416)
            response['Content-Range'] = f'bytes */{size}'
        else:
            stream.seek(start)
            response = StreamingHttpResponse(_read_range(stream, end - start + 1), status=206, content_type=content_type)
            response['Content-Length'] = str(end - start + 1)
            response['Content-Range'] = f'bytes {start}-{end}/{size}'
    else:
        response = FileResponse(stream, content_type=content_type)
    response['Accept-Ranges'] = 'bytes'
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = "default-src 'none'; media-src 'self'; img-src 'self'; sandbox"
    return response
