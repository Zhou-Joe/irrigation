"""Team feedback, private attachments and owner/administrator actions."""
import hashlib
import io
import logging
import uuid
from pathlib import Path

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, F
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django.utils import timezone
from PIL import Image, ImageOps

from .access import active_membership
from .models import Feedback, FeedbackPhoto, FeedbackAttachment, Team, AuditEvent

logger = logging.getLogger(__name__)
MAX_FILES = 10
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024


class PhotoInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class PhotosField(forms.ImageField):
    def __init__(self, **kwargs):
        super().__init__(widget=PhotoInput(attrs={'accept': 'image/jpeg,image/png,image/webp,image/gif,image/bmp',
            'aria-describedby': 'feedbackPhotoHelp'}), **kwargs)

    def clean(self, data, initial=None):
        files = data if isinstance(data, (list, tuple)) else [data] if data else []
        if len(files) > 5:
            raise forms.ValidationError('每条反馈最多上传 5 张照片。')
        for file in files:
            if file.size > 10 * 1024 * 1024:
                raise forms.ValidationError('每张照片不能超过 10 MB。')
        return [super(PhotosField, self).clean(file, initial) for file in files]


class AttachmentsField(forms.FileField):
    def __init__(self, **kwargs):
        super().__init__(widget=PhotoInput(attrs={'aria-describedby':'feedbackAttachmentHelp'}), **kwargs)

    def clean(self, data, initial=None):
        files = data if isinstance(data, (list, tuple)) else [data] if data else []
        if len(files) > MAX_FILES:
            raise forms.ValidationError('每条反馈最多上传 10 个附件。')
        result = []
        for upload in files:
            file = super().clean(upload, initial)
            if file.size > MAX_ATTACHMENT_BYTES:
                raise forms.ValidationError('单个附件不能超过 50 MB。')
            result.append(file)
        return result


class FeedbackForm(forms.Form):
    message = forms.CharField(label='反馈内容', max_length=5000, strip=True,
        widget=forms.Textarea(attrs={'rows': 7, 'placeholder': '描述遇到的问题，或希望改进的地方。也可以附上相关文件。',
            'aria-describedby': 'feedbackMessageHelp feedbackMessageCount'}))
    photos = PhotosField(label='添加照片', required=False)
    attachments = AttachmentsField(label='其他附件', required=False)
    submission_key = forms.UUIDField(widget=forms.HiddenInput)
    context_team = forms.IntegerField(widget=forms.HiddenInput)

    def clean(self):
        values = super().clean()
        files = values.get('photos', []) + values.get('attachments', [])
        if len(files) > MAX_FILES:
            raise forms.ValidationError('照片和其他附件合计最多 10 个。')
        if sum(file.size for file in files) > MAX_TOTAL_BYTES:
            raise forms.ValidationError('照片和附件合计不能超过 100 MB。')
        return values


def private_root():
    root = Path(getattr(settings, 'FEEDBACK_PRIVATE_ROOT', settings.BASE_DIR / 'private_feedback')).resolve()
    for public in (settings.MEDIA_ROOT, settings.STATIC_ROOT):
        if public and root.is_relative_to(Path(public).resolve()):
            raise ImproperlyConfigured('FEEDBACK_PRIVATE_ROOT must be outside media/static directories')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def member_for(request):
    member = active_membership(request)
    if not member:
        raise PermissionDenied('请先选择有效的团队身份再提交或查看反馈。')
    return member


def visible_feedback(request, member, *, include_deleted=False):
    qs = Feedback.objects.select_related('author', 'team__business').prefetch_related('photos', 'attachments')
    if not include_deleted:
        qs = qs.filter(deleted_at__isnull=True)
    return qs if request.user.is_superuser or request.user.is_staff else qs.filter(team=member.team)


def can_manage(request, member, item):
    return (item.author_id == request.user.pk or request.user.is_superuser or request.user.is_staff or
            item.team_id == member.team_id and member.role == 'manager')


def _fingerprint(team, text, photos, attachments=()):
    value = hashlib.sha256(f'{team.pk}\n{text}'.encode())
    for photo in photos:
        value.update(photo.name.encode())
        for chunk in photo.chunks():
            value.update(chunk)
        photo.seek(0)
    if attachments:
        value.update(b'\0attachments\0')
    for upload in attachments:
        value.update(f'{len(upload.name)}:{upload.name}:{upload.size}:'.encode())
        for chunk in upload.chunks():
            value.update(chunk)
        upload.seek(0)
    return value.hexdigest()


def _remove_files(names):
    if not names:
        return
    root = private_root()
    for name in names:
        path = root / name
        if not path.resolve().is_relative_to(root) or path.parent.is_symlink():
            logger.error('Refused invalid feedback storage path')
            continue
        try:
            path.unlink(missing_ok=True)
            try:
                path.parent.rmdir()
            except OSError:
                pass
        except OSError:
            logger.exception('Could not remove a detached feedback file')


def _save(request, member, form):
    values = form.cleaned_data
    if values['context_team'] != member.team_id:
        form.add_error(None, '团队视图已变化，请刷新页面后重新提交。')
        return False
    fingerprint = _fingerprint(member.team, values['message'], values['photos'], values['attachments'])
    existing = Feedback.objects.filter(author=request.user, submission_key=values['submission_key']).first()
    if existing:
        if existing.deleted_at:
            form.add_error(None, '这条反馈已删除，请刷新后重新提交。')
            return False
        if existing.fingerprint != fingerprint:
            form.add_error(None, '这次提交已有记录，修改后的内容尚未保存；请刷新页面后再提交。')
            return False
        return True
    feedback = Feedback(team=member.team, author=request.user, message=values['message'],
                        submission_key=values['submission_key'], fingerprint=fingerprint)
    written, photos, attachments = [], [], []
    folder = None
    try:
        # Decode/resize before opening the business write transaction.
        prepared = []
        for upload in values['photos']:
            with Image.open(upload) as original:
                image = ImageOps.exif_transpose(original)
                image.thumbnail((1920, 1920))
                output = io.BytesIO()
                image.convert('RGB').save(output, format='JPEG', quality=90)
                prepared.append(output.getvalue())
        if prepared or values['attachments']:
            folder = private_root() / str(feedback.pk)
            folder.mkdir(mode=0o700)
            for data in prepared:
                photo = FeedbackPhoto(feedback=feedback)
                photo.storage_name = f'{feedback.pk}/{photo.pk}.jpg'
                path = folder / f'{photo.pk}.jpg'
                written.append(photo.storage_name)
                path.write_bytes(data)
                path.chmod(0o600)
                photos.append(photo)
            for upload in values['attachments']:
                name = upload.name.replace('\\', '/').rsplit('/', 1)[-1]
                name = ''.join(char for char in name if ord(char) >= 32 and ord(char) != 127).strip()
                if not name or name in ('.', '..') or len(name) > 255:
                    raise ValueError('附件名称无效。')
                attachment = FeedbackAttachment(feedback=feedback, original_name=name, size=upload.size)
                attachment.storage_name = f'{feedback.pk}/{attachment.pk}.bin'
                path = private_root() / attachment.storage_name
                written.append(attachment.storage_name)
                with path.open('xb') as output:
                    for chunk in upload.chunks():
                        output.write(chunk)
                path.chmod(0o600)
                if path.stat().st_size != upload.size:
                    raise ValueError('附件大小不符。')
                attachments.append(attachment)
        with transaction.atomic():
            feedback.save(force_insert=True)
            FeedbackPhoto.objects.bulk_create(photos)
            FeedbackAttachment.objects.bulk_create(attachments)
        return True
    except IntegrityError:
        existing = Feedback.objects.filter(author=request.user, submission_key=values['submission_key']).first()
        if existing and not existing.deleted_at and existing.fingerprint == fingerprint:
            return True
        if existing:
            form.add_error(None, '这次提交已有不同内容，请刷新后核对记录。')
            return False
        raise
    except (OSError, ValueError, Image.DecompressionBombError):
        form.add_error(None, '照片或附件无法读取或保存，请检查文件后重新选择。')
        return False
    finally:
        if not Feedback.objects.filter(pk=feedback.pk).exists():
            _remove_files(written)
            if folder is not None:
                try:
                    folder.rmdir()
                except OSError:
                    pass


@login_required
@require_http_methods(['GET', 'POST'])
@never_cache
def board(request):
    member = member_for(request)
    form = FeedbackForm(request.POST or None, request.FILES or None, initial={
        'submission_key': uuid.uuid4(), 'context_team': member.team_id})
    if request.method == 'POST' and form.is_valid() and _save(request, member, form):
        messages.success(request, '反馈已收到，感谢你的建议。')
        return redirect('core:feedback')
    qs = visible_feedback(request, member)
    teams = list(qs.order_by('team__business__name', 'team__name').values(
        'team_id', 'team__name', 'team__business__name').annotate(total=Count('pk')))
    selected = request.GET.get('team', '')
    if selected:
        allowed = (selected.isdigit() and (Team.objects.filter(pk=int(selected)).exists()
                   if request.user.is_superuser or request.user.is_staff else int(selected) == member.team_id))
        if not allowed:
            raise Http404
        qs = qs.filter(team_id=int(selected))
    page = Paginator(qs, 20).get_page(request.GET.get('page'))
    for item in page:
        item.can_manage = can_manage(request, member, item)
    return render(request, 'core/feedback.html', {'feedback_form': form,
        'feedback_team': member.team, 'feedback_teams': teams, 'selected_team': selected,
        'feedback_page': page},
        status=400 if request.method == 'POST' else 200)


@login_required
@require_GET
@never_cache
def photo(request, photo_id):
    member = member_for(request)
    item = get_object_or_404(FeedbackPhoto.objects.filter(feedback__in=visible_feedback(request, member)), pk=photo_id)
    root = private_root()
    path = _stored_path(item, root, '.jpg')
    response = FileResponse(path.open('rb'), content_type='image/jpeg')
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def _stored_path(item, root, suffix):
    if item.storage_name != f'{item.feedback_id}/{item.pk}{suffix}':
        raise Http404
    path = root / item.storage_name
    if not path.resolve().is_relative_to(root) or path.parent.is_symlink() or path.is_symlink() or not path.is_file():
        raise Http404
    return path


@login_required
@require_GET
@never_cache
def attachment(request, attachment_id):
    member = member_for(request)
    item = get_object_or_404(FeedbackAttachment.objects.filter(feedback__in=visible_feedback(request, member)), pk=attachment_id)
    path = _stored_path(item, private_root(), '.bin')
    # Every arbitrary attachment is a download, never executable app-origin content.
    response = FileResponse(path.open('rb'), content_type='application/octet-stream',
                            as_attachment=True, filename=item.original_name)
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = "default-src 'none'; sandbox"
    return response


def _context_changed(request, member):
    return request.POST.get('context_team') != str(member.team_id)


@login_required
@require_POST
@never_cache
def action(request, feedback_id):
    member = member_for(request)
    if _context_changed(request, member):
        return JsonResponse({'success':False,'message':'团队视图已变化，请刷新后重试。'},status=409)
    operation = request.POST.get('action')
    item = get_object_or_404(visible_feedback(request, member, include_deleted=operation=='delete'), pk=feedback_id)
    if not can_manage(request, member, item):
        raise PermissionDenied('只有提出者或管理员可以修改这条反馈。')
    if operation not in ('status', 'delete'):
        return JsonResponse({'success':False,'message':'操作无效。'},status=400)
    status = request.POST.get('status')
    if operation=='status' and status not in dict(Feedback.STATUS_CHOICES):
        return JsonResponse({'success':False,'message':'请核对反馈状态。'},status=400)
    with transaction.atomic():
        # Claim the write before reading child files, including on SQLite.
        locked = Feedback.objects.filter(pk=item.pk, deleted_at__isnull=True).update(status=F('status'))
        if not locked:
            if operation=='delete':
                return JsonResponse({'success':True,'deleted':True,'team_id':item.team_id})
            raise Http404
        item.refresh_from_db(fields=['status','deleted_at'])
        if operation=='status':
            previous = item.status
            Feedback.objects.filter(pk=item.pk).update(status=status)
            AuditEvent.objects.create(team=item.team,actor=request.user,action='feedback.status',object_ref=str(item.pk),
                                      detail={'previous':previous,'status':status})
            return JsonResponse({'success':True,'status':status,'label':dict(Feedback.STATUS_CHOICES)[status]})
        names = list(FeedbackPhoto.objects.filter(feedback=item).values_list('storage_name',flat=True))
        names += list(FeedbackAttachment.objects.filter(feedback=item).values_list('storage_name',flat=True))
        Feedback.objects.filter(pk=item.pk).update(deleted_at=timezone.now())
        FeedbackPhoto.objects.filter(feedback=item).delete()
        FeedbackAttachment.objects.filter(feedback=item).delete()
        AuditEvent.objects.create(team=item.team,actor=request.user,action='feedback.delete',object_ref=str(item.pk))
        transaction.on_commit(lambda:_remove_files(names))
    return JsonResponse({'success':True,'deleted':True,'team_id':item.team_id})


@login_required
@require_POST
@never_cache
def file_delete(request, feedback_id, kind, file_id):
    member = member_for(request)
    if _context_changed(request, member):
        return JsonResponse({'success':False,'message':'团队视图已变化，请刷新后重试。'},status=409)
    item = get_object_or_404(visible_feedback(request, member), pk=feedback_id)
    if not can_manage(request, member, item):
        raise PermissionDenied('只有提出者或管理员可以删除附件。')
    model = {'photos':FeedbackPhoto,'attachments':FeedbackAttachment}.get(kind)
    if model is None:
        raise Http404
    with transaction.atomic():
        if not Feedback.objects.filter(pk=item.pk,deleted_at__isnull=True).update(status=F('status')):
            raise Http404
        file = get_object_or_404(model,feedback=item,pk=file_id)
        name = file.storage_name
        file.delete()
        AuditEvent.objects.create(team=item.team,actor=request.user,action='feedback.file.delete',object_ref=str(item.pk),
                                  detail={'kind':kind,'file_id':str(file_id)})
        transaction.on_commit(lambda:_remove_files([name]))
    return JsonResponse({'success':True,'file_deleted':True})
