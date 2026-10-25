"""Keep session and token account deactivation consistent; JSON on API expiry."""
from django.contrib.auth import logout
from django.http import JsonResponse
from django.shortcuts import redirect
from .role_utils import get_user_role


def wants_json(request):
    return request.path.startswith('/api/') or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', '')


class SessionGuardMiddleware:
    def __init__(self, get_response):
        self.get_response=get_response

    def __call__(self, request):
        if request.user.is_authenticated and get_user_role(request.user) is None:
            logout(request)
            if wants_json(request):
                return JsonResponse({'success':False,'error':'账号已停用，请联系管理员','message':'账号已停用，请联系管理员'},status=401)
            return redirect('core:login')
        response=self.get_response(request)
        if response.status_code==302 and wants_json(request) and '/login/' in response.get('Location',''):
            return JsonResponse({'success':False,'error':'登录已过期，请重新登录','message':'登录已过期，请重新登录','login_url':'/login/'},status=401)
        return response

    def process_exception(self,request,exception):
        from django.core.exceptions import PermissionDenied
        if isinstance(exception,PermissionDenied) and wants_json(request):
            return JsonResponse({'success':False,'error':str(exception) or '无权限','message':str(exception) or '无权限'},status=403)


def set_account_enabled(user, enabled):
    from django.contrib.sessions.models import Session
    from django.utils import timezone
    from .models import Worker, ManagerProfile, DepartmentUserProfile
    import uuid
    user.is_active=enabled;user.save(update_fields=['is_active'])
    for model in (Worker,ManagerProfile,DepartmentUserProfile):
        changes={'active':enabled}
        if not enabled:changes['api_token']=uuid.uuid4()
        model.objects.filter(user=user).update(**changes)
    if not enabled:
        ids=[s.session_key for s in Session.objects.filter(expire_date__gt=timezone.now())
             if str(s.get_decoded().get('_auth_user_id',''))==str(user.pk)]
        Session.objects.filter(session_key__in=ids).delete()
