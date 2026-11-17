"""SMTP or M365 HTTP Workflow; private report downloads replace workflow attachments."""
import hashlib
import secrets
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator, validate_email
from django.http import FileResponse, Http404
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape, format_html
from django.views.decorators.http import require_safe

from .models import EmailSmtpSetting, EmailReportFile, EmailDeliveryProfile
from .report_export import XLSX_CT

RETENTION_DAYS = 7


def validate_workflow_url(value):
    URLValidator(schemes=['https'])(value)
    parsed=urlsplit(value);host=(parsed.hostname or '').lower()
    if (parsed.username or parsed.password or parsed.fragment or parsed.port not in (None,443)
        or not any(host.endswith(suffix) for suffix in ('.logic.azure.com','.logic.azure.cn','.environment.api.powerplatform.com','.environment.api.powerplatform.cn'))):
        raise ValidationError('请填写 Microsoft Power Automate 的 HTTPS HTTP 触发链接。')


def validate_download_base(value):
    URLValidator(schemes=['https'])(value)
    parsed=urlsplit(value)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValidationError('下载站点请填写 HTTPS 网站地址，不包含查询参数。')


def public_download_base(request=None):
    """System-owned public origin, shared by cron and interactive account/report mail."""
    configured=getattr(settings,'EMAIL_REPORT_PUBLIC_BASE_URL','').strip()
    if configured:
        validate_download_base(configured);return configured.rstrip('/')
    if request is not None:
        import ipaddress
        host=request.get_host();hostname=(urlsplit('https://'+host).hostname or '').lower()
        try:public=ipaddress.ip_address(hostname).is_global
        except ValueError:public='.' in hostname and not hostname.endswith(('.localhost','.local'))
        if public:return 'https://'+host
    stored=EmailSmtpSetting.get_solo().download_base_url
    if stored:
        try:validate_download_base(stored);return stored.rstrip('/')
        except ValidationError:pass
    return 'https://irrigation.zctestbench.asia'


def resolve_profile(profile=None):
    if profile is not None:return profile
    legacy=EmailSmtpSetting.get_solo()
    return legacy.default_profile or legacy


def is_configured(profile=None):
    setting=resolve_profile(profile)
    if setting.delivery_method=='workflow':return bool(setting.workflow_url)
    if isinstance(setting,EmailDeliveryProfile):
        return bool(getattr(settings,'EMAIL_HOST','')) if setting.use_environment else bool(setting.host)
    from .smtp_utils import is_smtp_configured
    return is_smtp_configured()


def file_root():
    return Path(getattr(settings,'EMAIL_REPORT_PRIVATE_ROOT',settings.BASE_DIR/'private_email_reports'))


def file_path(file_id):
    root=file_root().resolve();path=root/file_id.hex
    if not path.resolve().is_relative_to(root):raise ValueError('Invalid report file path')
    return path


def purge_expired_files():
    for record in EmailReportFile.objects.filter(expires_at__lte=timezone.now()).iterator():
        file_path(record.pk).unlink(missing_ok=True);record.delete()


def _download_link(filename,content,base):
    token=secrets.token_urlsafe(32)
    record=EmailReportFile(filename=Path(str(filename).replace('\\','/')).name[:255],
        token_hash=hashlib.sha256(token.encode()).hexdigest(),expires_at=timezone.now()+timedelta(days=RETENTION_DAYS))
    root=file_root();root.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=file_path(record.pk)
    try:
        with path.open('xb') as output:output.write(content)
        path.chmod(0o600);record.save(force_insert=True)
    except Exception:
        path.unlink(missing_ok=True);raise
    return base.rstrip('/')+reverse('core:email_report_download',args=[record.pk,token])


def send_report(subject,body,recipients,attachments,*,profile=None,html_body=None):
    """attachments: iterable of (filename, bytes, MIME type). No automatic send retries."""
    setting=resolve_profile(profile)
    recipients=list(dict.fromkeys(value.strip() for value in recipients if value.strip()))
    if not recipients:raise ValueError('未提供收件人')
    for recipient in recipients:validate_email(recipient)
    attachments=list(attachments)
    if setting.delivery_method!='workflow':
        from django.core.mail import EmailMessage
        from .smtp_utils import get_email_connection, resolve_from_email
        if isinstance(setting,EmailDeliveryProfile):
            from django.core.mail import get_connection
            if not is_configured(setting):raise ValueError('所选 SMTP 发送配置尚未完善')
            connection=get_connection() if setting.use_environment else get_connection(host=setting.host,port=setting.port,username=setting.username or None,password=setting.password or None,use_ssl=setting.use_ssl,use_tls=setting.use_tls,timeout=getattr(settings,'EMAIL_TIMEOUT',30))
            sender=(getattr(settings,'DEFAULT_FROM_EMAIL','') if setting.use_environment else setting.from_email or setting.username or getattr(settings,'DEFAULT_FROM_EMAIL',''))
        else:connection=get_email_connection();sender=resolve_from_email()
        if html_body is not None:
            from django.core.mail import EmailMultiAlternatives
            message=EmailMultiAlternatives(subject=subject,body=body,from_email=sender,to=recipients,connection=connection);message.attach_alternative(html_body,'text/html')
        else:message=EmailMessage(subject=subject,body=body,from_email=sender,to=recipients,connection=connection)
        for filename,content,mime in attachments:message.attach(filename,content,mime)
        if message.send(fail_silently=False)!=1:raise ValueError('邮件未确认发送成功')
        return {'method':'smtp','status':'sent','message':'邮件已发送'}
    if not setting.workflow_url:raise ValueError('请先配置 Microsoft 365 Workflow HTTP 链接')
    validate_workflow_url(setting.workflow_url)
    base=public_download_base()
    validate_download_base(base);purge_expired_files()
    links=[]
    for filename,content,mime in attachments:
        url=_download_link(filename,content,base)
        links.append(str(format_html('<li style="margin:10px 0"><a href="{}">{}</a> <span style="color:#607269">({} KB)</span></li>',url,filename,max(1,round(len(content)/1024)))))
    text=html_body if html_body is not None else escape(body.replace('请见附件','请使用下方报表下载链接')).replace('\n','<br>')
    html='<div style="font:14px/1.7 Arial,sans-serif;color:#243d30">'+text
    if links:html+='<h3 style="margin-top:24px">报表下载</h3><ul>'+''.join(links)+'</ul><p style="color:#607269">下载链接自发送起 7 天内有效。</p>'
    html+='</div>'
    try:
        response=requests.post(setting.workflow_url,json={'t':';'.join(recipients),'s':subject,'b':html},timeout=(10,60),allow_redirects=False)
    except requests.RequestException:
        # Request exceptions can contain the secret trigger URL. Never expose it.
        raise ValueError('Workflow 连接失败或响应超时，发送结果尚未确认，请先查看流程运行记录。') from None
    status=response.status_code;response.close()
    if not 200<=status<300:raise ValueError(f'Workflow 返回 HTTP {status}，请检查触发链接、认证及 t/s/b 参数映射。')
    return {'method':'workflow','status':'accepted','message':'已提交 Microsoft 365 Workflow（实际投递结果见流程运行记录）'}


@require_safe
def download(request,file_id,token):
    record=EmailReportFile.objects.filter(pk=file_id,token_hash=hashlib.sha256(token.encode()).hexdigest(),expires_at__gt=timezone.now()).first()
    if not record:raise Http404('下载链接已过期或失效')
    try:stream=file_path(record.pk).open('rb')
    except FileNotFoundError:raise Http404('报表文件已失效') from None
    response=FileResponse(stream,as_attachment=True,filename=record.filename,content_type=XLSX_CT)
    response['Cache-Control']='private, no-store';response['X-Content-Type-Options']='nosniff';response['Referrer-Policy']='no-referrer'
    return response
