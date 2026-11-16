"""Team feedback and privately served, validated illustration photos."""
import hashlib
import io
import uuid
from pathlib import Path

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods
from PIL import Image, ImageOps

from .access import active_membership
from .models import Feedback, FeedbackPhoto


class PhotoInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class PhotosField(forms.ImageField):
    def __init__(self, **kwargs):
        super().__init__(widget=PhotoInput(attrs={'accept': 'image/jpeg,image/png,image/webp,image/gif,image/bmp'}), **kwargs)

    def clean(self, data, initial=None):
        files = data if isinstance(data, (list, tuple)) else [data] if data else []
        if len(files) > 5:
            raise forms.ValidationError('每条反馈最多上传 5 张照片。')
        for file in files:
            if file.size > 10 * 1024 * 1024:
                raise forms.ValidationError('每张照片不能超过 10 MB。')
        return [super(PhotosField, self).clean(file, initial) for file in files]


class FeedbackForm(forms.Form):
    message = forms.CharField(label='反馈内容', max_length=5000, strip=True,
        widget=forms.Textarea(attrs={'rows': 7, 'placeholder': '描述遇到的问题，或希望改进的地方。也可以附上照片说明。'}))
    photos = PhotosField(label='添加照片', required=False)
    submission_key = forms.UUIDField(widget=forms.HiddenInput)
    context_team = forms.IntegerField(widget=forms.HiddenInput)


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


def visible_feedback(request, member):
    qs = Feedback.objects.select_related('author', 'team__business').prefetch_related('photos')
    return qs if request.user.is_superuser or request.user.is_staff else qs.filter(team=member.team)


def _fingerprint(team, text, photos):
    value = hashlib.sha256(f'{team.pk}\n{text}'.encode())
    for photo in photos:
        value.update(photo.name.encode())
        for chunk in photo.chunks():
            value.update(chunk)
        photo.seek(0)
    return value.hexdigest()


def _save(request, member, form):
    values = form.cleaned_data
    if values['context_team'] != member.team_id:
        form.add_error(None, '团队视图已变化，请刷新页面后重新提交。')
        return False
    fingerprint = _fingerprint(member.team, values['message'], values['photos'])
    existing = Feedback.objects.filter(author=request.user, submission_key=values['submission_key']).first()
    if existing:
        if existing.fingerprint != fingerprint:
            form.add_error(None, '这次提交已有记录，修改后的内容尚未保存；请刷新页面后再提交。')
            return False
        return True
    feedback = Feedback(team=member.team, author=request.user, message=values['message'],
                        submission_key=values['submission_key'], fingerprint=fingerprint)
    written, photos = [], []
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
        if prepared:
            folder = private_root() / str(feedback.pk)
            folder.mkdir(mode=0o700)
            for data in prepared:
                photo = FeedbackPhoto(feedback=feedback)
                photo.storage_name = f'{feedback.pk}/{photo.pk}.jpg'
                path = folder / f'{photo.pk}.jpg'
                path.write_bytes(data)
                written.append(path)
                photos.append(photo)
        with transaction.atomic():
            feedback.save(force_insert=True)
            FeedbackPhoto.objects.bulk_create(photos)
        return True
    except IntegrityError:
        existing = Feedback.objects.filter(author=request.user, submission_key=values['submission_key']).first()
        if existing and existing.fingerprint == fingerprint:
            return True
        if existing:
            form.add_error(None, '这次提交已有不同内容，请刷新后核对记录。')
            return False
        raise
    except (OSError, ValueError, Image.DecompressionBombError):
        form.add_error('photos', '照片无法读取或保存，请检查文件后重新选择。')
        return False
    finally:
        if not Feedback.objects.filter(pk=feedback.pk).exists():
            for path in written:
                path.unlink(missing_ok=True)
            if written:
                written[0].parent.rmdir()


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
        if not selected.isdigit() or int(selected) not in {item['team_id'] for item in teams}:
            raise Http404
        qs = qs.filter(team_id=int(selected))
    return render(request, 'core/feedback.html', {'feedback_form': form,
        'feedback_team': member.team, 'feedback_teams': teams, 'selected_team': selected,
        'feedback_page': Paginator(qs, 20).get_page(request.GET.get('page'))},
        status=400 if request.method == 'POST' else 200)


@login_required
@require_GET
@never_cache
def photo(request, photo_id):
    member = member_for(request)
    item = get_object_or_404(FeedbackPhoto.objects.filter(feedback__in=visible_feedback(request, member)), pk=photo_id)
    root = private_root()
    path = root / item.storage_name
    if not path.resolve().is_relative_to(root) or path.is_symlink() or not path.is_file():
        raise Http404
    response = FileResponse(path.open('rb'), content_type='image/jpeg')
    response['X-Content-Type-Options'] = 'nosniff'
    return response
