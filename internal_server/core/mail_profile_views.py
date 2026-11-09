"""Named, reusable mail delivery settings. Secrets are write-only in this API."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from .models import EmailDeliveryProfile, EmailSmtpSetting
from .mail_delivery import is_configured, validate_workflow_url, validate_download_base


def permitted(request):
    from .views import _email_config_perm
    return _email_config_perm(request)


def serialize(profile,default_id):
    return {'id':profile.pk,'name':profile.name,'delivery_method':profile.delivery_method,
        'host':profile.host,'port':profile.port,'username':profile.username,'from_email':profile.from_email,
        'use_ssl':profile.use_ssl,'use_tls':profile.use_tls,'use_environment':profile.use_environment,
        'has_password':bool(profile.password),'has_workflow_url':bool(profile.workflow_url),
        'download_base_url':profile.download_base_url,'is_default':profile.pk==default_id,
        'is_configured':is_configured(profile)}


@login_required(login_url='core:login')
@require_GET
def profiles(request):
    if not permitted(request):return JsonResponse({'success':False,'message':'无权限'},status=403)
    default_id=EmailSmtpSetting.get_solo().default_profile_id
    return JsonResponse({'success':True,'default_profile_id':default_id,
        'profiles':[serialize(p,default_id) for p in EmailDeliveryProfile.objects.order_by('name','id')]})


@login_required(login_url='core:login')
@require_POST
def save(request):
    if not permitted(request):return JsonResponse({'success':False,'message':'无权限'},status=403)
    identifier=request.POST.get('id','').strip()
    profile=get_object_or_404(EmailDeliveryProfile,pk=identifier) if identifier.isdigit() else EmailDeliveryProfile()
    if identifier and not identifier.isdigit():return JsonResponse({'success':False,'message':'发送配置无效'},status=400)
    profile.name=(request.POST.get('name') or '').strip()
    profile.delivery_method=request.POST.get('delivery_method','smtp')
    try:
        if not profile.name or len(profile.name)>100:raise ValidationError('请填写配置名称（最多 100 字）。')
        if profile.delivery_method not in ('smtp','workflow'):raise ValidationError('发送方式无效。')
        if profile.delivery_method=='workflow':
            profile.workflow_url=(request.POST.get('workflow_url') or '').strip() or profile.workflow_url
            if not profile.workflow_url:raise ValidationError('请填写 Workflow HTTP 链接。')
            validate_workflow_url(profile.workflow_url)
            profile.download_base_url=(request.POST.get('download_base_url') or '').strip()
            if profile.download_base_url:validate_download_base(profile.download_base_url)
        else:
            profile.host=(request.POST.get('host') or '').strip()
            if not profile.host and not profile.use_environment:raise ValidationError('请填写 SMTP 服务器。')
            profile.port=int(request.POST.get('port') or 465)
            if not 1<=profile.port<=65535:raise ValidationError('SMTP 端口必须在 1–65535 之间。')
            profile.username=(request.POST.get('username') or '').strip()
            if request.POST.get('password'):profile.password=request.POST['password']
            encryption=request.POST.get('encryption','ssl')
            if encryption not in ('ssl','tls','none'):raise ValidationError('加密方式无效。')
            profile.use_ssl=encryption=='ssl';profile.use_tls=encryption=='tls'
            profile.from_email=(request.POST.get('from_email') or '').strip()
            if profile.from_email:validate_email(profile.from_email)
            if profile.host:profile.use_environment=False
        profile.full_clean(validate_unique=False)
        with transaction.atomic():
            profile.save()
            setting=EmailSmtpSetting.get_solo()
            if request.POST.get('set_default')=='1' or not setting.default_profile_id:
                setting.default_profile=profile;setting.save(update_fields=['default_profile'])
        return JsonResponse({'success':True,'message':'发送配置已保存','profile':serialize(profile,setting.default_profile_id)})
    except (ValidationError,ValueError) as error:
        message='；'.join(error.messages) if isinstance(error,ValidationError) else '请检查端口和链接格式。'
        return JsonResponse({'success':False,'message':message},status=400)
    except IntegrityError:return JsonResponse({'success':False,'message':'配置名称已存在，请使用其他名称。'},status=409)


@login_required(login_url='core:login')
@require_POST
def delete(request,pk):
    if not permitted(request):return JsonResponse({'success':False,'message':'无权限'},status=403)
    profile=get_object_or_404(EmailDeliveryProfile,pk=pk)
    try:profile.delete()
    except ProtectedError:
        return JsonResponse({'success':False,'message':'该配置是默认配置或正被报表使用，请先改选其他配置。'},status=409)
    return JsonResponse({'success':True,'message':'发送配置已删除'})
