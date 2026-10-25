"""Durable submission receipts: a lost HTTP response cannot duplicate a write."""
import hashlib
import json
import uuid
from functools import wraps
from django.db import transaction, IntegrityError, OperationalError
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from .models import SubmissionReceipt
from .role_utils import get_django_user


def fingerprint(request):
    data=[(key,values) for key,values in sorted(request.POST.lists()) if key not in ('csrfmiddlewaretoken','submission_key')]
    digest=hashlib.sha256(json.dumps(data,ensure_ascii=False).encode())
    for name,files in sorted(request.FILES.lists()):
        for file in files:
            digest.update((name+file.name+str(file.size)).encode())
            position=file.tell()
            for chunk in file.chunks():digest.update(chunk)
            file.seek(position)
    return digest.hexdigest()


def replay(item):
    if item.status_code==302:
        response=HttpResponse(status=302);response['Location']=item.response['location']
    else:
        response=JsonResponse(item.response,status=item.status_code)
    response['Idempotency-Replayed']='true'
    return response


def submission(kind):
    def decorate(view):
        @wraps(view)
        def wrapped(request,*args,**kwargs):
            raw=request.headers.get('X-Submission-Key') or request.POST.get('submission_key')
            owner=get_django_user(request.user)
            if request.method!='POST' or not raw or not owner:
                return view(request,*args,**kwargs)
            try:key=uuid.UUID(raw)
            except (ValueError,TypeError,AttributeError):
                return JsonResponse({'success':False,'message':'提交编号无效，请重新打开表单'},status=400)
            signature=fingerprint(request)
            def existing():
                item=SubmissionReceipt.objects.filter(owner=owner,key=key).first()
                if item:
                    if item.kind!=kind or item.fingerprint!=signature:
                        return JsonResponse({'success':False,'message':'此编号已有提交结果；当前修改尚未保存，请先核对原记录。'},status=409)
                    return replay(item)
            previous=existing()
            if previous:return previous
            try:
                with transaction.atomic():
                    item=SubmissionReceipt.objects.create(owner=owner,key=key,kind=kind,fingerprint=signature)
                    response=view(request,*args,**kwargs)
                    result=None
                    if response.status_code==302:
                        # Only successful redirects from these forms are stored;
                        # validation renders HTML or returns an error status.
                        result={'location':response['Location']}
                    elif response.get('Content-Type','').startswith('application/json'):
                        result=json.loads(response.content)
                        if not result.get('success'):result=None
                    if result is None or response.status_code>=400:
                        item.delete()
                    else:
                        item.response=result;item.status_code=response.status_code
                        item.save(update_fields=['response','status_code'])
                    return response
            except IntegrityError:
                return existing() or JsonResponse({'success':False,'message':'提交正在处理中，请用相同内容重试。'},status=409)
            except OperationalError as exc:
                if 'locked' not in str(exc).lower():raise
                return JsonResponse({'success':False,'uncertain':True,'message':'提交结果待确认，请保留表单并核对记录。'},status=409)
        return wrapped
    return decorate


@login_required(login_url='core:login')
def result(request,key):
    item=SubmissionReceipt.objects.filter(owner=get_django_user(request.user),key=key).first()
    if not item:return JsonResponse({'found':False,'message':'暂未找到已完成结果，请稍后核对或用原内容重试。'})
    return JsonResponse({'found':True,'kind':item.kind,'result':item.response,'status':item.status_code})
