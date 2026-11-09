"""Account mail uses administrator-selected saved delivery profiles."""
import hashlib
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from django import forms
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import PasswordResetConfirmView
from django.core import signing
from django.core.cache import cache
from django.db import close_old_connections
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.html import format_html
from django.utils.http import urlsafe_base64_encode
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .models import AccountEmailSetting, EmailDeliveryProfile, EmailSmtpSetting, RegistrationRequest
from .mail_delivery import is_configured, public_download_base, send_report

logger=logging.getLogger(__name__)
_pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='account-mail')
_slots=threading.BoundedSemaphore(64)
SALT='core.registration-email'


class EmailRequestForm(forms.Form):
    email=forms.EmailField(label='账号邮箱',widget=forms.EmailInput(attrs={'autocomplete':'email','placeholder':'请输入账号中登记的邮箱'}))


class ConfirmationRequestForm(EmailRequestForm):
    username=forms.CharField(label='注册用户名',max_length=150)


def _worker(function,args):
    close_old_connections()
    try:function(*args)
    except Exception as error:logger.warning('Account email delivery failed (%s/%s)',function.__name__,type(error).__name__)
    finally:close_old_connections();_slots.release()


def _queue(request,purpose,email,function,*args):
    digest=hashlib.sha256(email.casefold().encode()).hexdigest()
    if not cache.add('account-mail:'+purpose+':'+digest,True,300):return
    ip=hashlib.sha256(request.META.get('REMOTE_ADDR','').encode()).hexdigest()
    key='account-mail-ip:'+ip+':'+str(int(time.time())//60)
    cache.add(key,0,90)
    try:count=cache.incr(key)
    except ValueError:count=1
    if count>20 or not _slots.acquire(blocking=False):return
    try:_pool.submit(_worker,function,args)
    except Exception:_slots.release();logger.warning('Account email queue unavailable')


def _registration_message(registration_id,profile_id,base):
    reg=RegistrationRequest.objects.filter(pk=registration_id,status='pending',email_confirmation_required=True,email_verified_at__isnull=True).first()
    if not reg:return
    token=signing.dumps({'registration':reg.pk,'email':reg.email},salt=SALT,compress=True)
    link=base+reverse('core:account_registration_verify',args=[token])
    text=f'请确认注册账号 {reg.username} 使用的邮箱：\n{link}\n\n链接 24 小时有效。确认后仍需管理员审批。非本人申请可忽略。'
    html=format_html('<p>您好，{}：</p><p>请确认注册账号 <strong>{}</strong> 使用的邮箱。</p><p><a href="{}">确认邮箱</a></p><p>链接 24 小时有效，确认后仍需管理员审批。非本人申请可忽略。</p>',reg.full_name,reg.username,link)
    send_report('FOS · 注册邮箱确认',text,[reg.email],[],profile=EmailDeliveryProfile.objects.get(pk=profile_id),html_body=html)


def send_registration(request,reg,profile_id):
    _queue(request,'registration',reg.email,_registration_message,reg.pk,profile_id,public_download_base(request))


def _reset_message(email,profile_id,base):
    profile=EmailDeliveryProfile.objects.get(pk=profile_id)
    for user in PasswordResetForm().get_users(email):
        uid=urlsafe_base64_encode(force_bytes(user.pk));token=default_token_generator.make_token(user)
        link=base+reverse('core:account_password_confirm',kwargs={'uidb64':uid,'token':token})
        text=f'账号 {user.get_username()} 的密码重置链接：\n{link}\n\n链接 1 小时有效，使用后失效。非本人申请可忽略。'
        html=format_html('<p>您好：</p><p>您可以为账号 <strong>{}</strong> 设置新密码。</p><p><a href="{}">重置密码</a></p><p>链接 1 小时有效，使用后失效。非本人申请可忽略。</p>',user.get_username(),link)
        send_report('FOS · 重置密码',text,[user.email],[],profile=profile,html_body=html)


@login_required(login_url='core:login')
@require_http_methods(['GET','POST'])
def settings_view(request):
    from .views import _email_config_perm
    if not _email_config_perm(request):return JsonResponse({'success':False,'message':'无权限'},status=403)
    config=AccountEmailSetting.get_solo()
    if request.method=='POST':
        values={}
        for field in ('registration_profile','password_reset_profile'):
            value=request.POST.get(field,'')
            profile=EmailDeliveryProfile.objects.filter(pk=int(value)).first() if value.isdigit() else None
            if value and (profile is None or not is_configured(profile)):
                return JsonResponse({'success':False,'message':'请选择已完善的发送配置，或选择不启用。'},status=400)
            values[field]=profile
        for field,value in values.items():setattr(config,field,value)
        config.save()
        system=EmailSmtpSetting.get_solo();system.download_base_url=public_download_base(request);system.save(update_fields=['download_base_url'])
    return JsonResponse({'success':True,'message':'账户邮件设置已保存',
        'registration_profile_id':config.registration_profile_id,'password_reset_profile_id':config.password_reset_profile_id})


@never_cache
@require_http_methods(['GET','POST'])
def password_request(request):
    config=AccountEmailSetting.get_solo();enabled=bool(config.password_reset_profile_id and is_configured(config.password_reset_profile))
    form=EmailRequestForm(request.POST if request.method=='POST' else None)
    message=''
    if request.method=='POST' and enabled and form.is_valid():
        email=form.cleaned_data['email']
        _queue(request,'reset',email,_reset_message,email,config.password_reset_profile_id,public_download_base(request))
        message='如该邮箱对应有效账号，重置邮件将发送至邮箱。请查收；未收到可稍后重试。'
        if request.headers.get('X-Requested-With')=='XMLHttpRequest':return JsonResponse({'success':True,'message':message})
        return redirect('core:account_password_sent')
    if request.method=='POST' and request.headers.get('X-Requested-With')=='XMLHttpRequest':
        return JsonResponse({'success':False,'message':'请填写有效邮箱。' if enabled else '管理员尚未启用密码重置邮件，请联系管理员。'},status=400)
    return render(request,'core/account_mail.html',{'title':'找回密码','mode':'request','form':form if enabled else None,
        'note':'使用账号中已登记的邮箱，同一邮箱每 5 分钟可申请一次。未登记邮箱请联系管理员。' if enabled else '管理员尚未启用密码重置邮件，请联系管理员。'})


@never_cache
@require_http_methods(['GET','POST'])
def resend_confirmation(request):
    config=AccountEmailSetting.get_solo();enabled=bool(config.registration_profile_id and is_configured(config.registration_profile))
    form=ConfirmationRequestForm(request.POST if request.method=='POST' else None)
    if request.method=='POST' and enabled and form.is_valid():
        # Lookup also stays in the background: response does not disclose registrations.
        def send_if_pending(username,email,profile_id,base):
            reg=RegistrationRequest.objects.filter(username=username,email__iexact=email,status='pending',email_confirmation_required=True,email_verified_at__isnull=True).first()
            if reg:_registration_message(reg.pk,profile_id,base)
        email=form.cleaned_data['email']
        _queue(request,'registration',email,send_if_pending,form.cleaned_data['username'],email,config.registration_profile_id,public_download_base(request))
        message='如信息对应待确认的注册申请，确认邮件将发送至邮箱。请查收；未收到可稍后重试。'
        if request.headers.get('X-Requested-With')=='XMLHttpRequest':return JsonResponse({'success':True,'message':message})
        return render(request,'core/account_mail.html',{'title':'确认邮件已申请','note':message})
    if request.method=='POST' and request.headers.get('X-Requested-With')=='XMLHttpRequest':
        return JsonResponse({'success':False,'message':'请检查用户名和邮箱。' if enabled else '注册邮箱确认尚未启用。'},status=400)
    return render(request,'core/account_mail.html',{'title':'重发注册确认邮件','mode':'request','form':form if enabled else None,
        'note':'填写注册时的用户名和邮箱。同一邮箱每 5 分钟可申请一次。' if enabled else '注册邮箱确认尚未启用。'})


@never_cache
@require_http_methods(['GET','POST'])
def verify_registration(request,token):
    reg=None
    try:
        payload=signing.loads(token,salt=SALT,max_age=86400)
        reg=RegistrationRequest.objects.filter(pk=payload['registration'],email=payload['email'],email_confirmation_required=True).first()
    except (signing.BadSignature,KeyError,TypeError,ValueError):pass
    if reg is None:return render(request,'core/account_mail.html',{'title':'确认链接已失效','note':'链接可能已过期，请重新申请确认邮件。','resend':True},status=400)
    if reg.email_verified_at:return render(request,'core/account_mail.html',{'title':'邮箱已确认','note':'请等待管理员审批注册申请。'})
    if reg.status!='pending':return render(request,'core/account_mail.html',{'title':'注册申请已处理','note':'无需再次确认邮箱。'})
    if request.method=='POST':
        RegistrationRequest.objects.filter(pk=reg.pk,status='pending',email=reg.email,email_verified_at__isnull=True).update(email_verified_at=timezone.now())
        return render(request,'core/account_mail.html',{'title':'邮箱确认成功','note':'注册申请仍需管理员审批，通过后即可登录。'})
    response=render(request,'core/account_mail.html',{'title':'确认注册邮箱','mode':'verify','note':'确认后，注册申请将继续等待管理员审批。'})
    response['Referrer-Policy']='no-referrer'
    return response


class ResetConfirmView(PasswordResetConfirmView):
    template_name='core/account_mail.html'
    success_url=reverse_lazy('core:account_password_complete')
    extra_context={'title':'设置新密码','mode':'confirm'}
