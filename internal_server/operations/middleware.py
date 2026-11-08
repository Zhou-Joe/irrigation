"""Pilot boundary: new teams cannot reach unscoped legacy business endpoints."""
from django.conf import settings
from django.http import HttpResponseNotFound, JsonResponse
from django.shortcuts import redirect


class BusinessAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        is_ops = request.path == '/ops' or request.path.startswith('/ops/')
        request.operations_shell = is_ops
        if not settings.MULTI_TEAM_ENABLED:
            return HttpResponseNotFound() if is_ops else self.get_response(request)
        if is_ops:
            response = self.get_response(request)
            response['Cache-Control'] = 'private, no-store'
            response['Vary'] = 'Cookie'
            return response
        if request.path in ('/login/', '/logout/', '/register/'):
            request.operations_shell = True
            return self.get_response(request)
        if request.path.startswith('/static/') or request.path in ('/manifest.webmanifest', '/service-worker.js', '/offline/'):
            return self.get_response(request)
        from .access import has_irrigation_access
        user = request.user
        if not user.is_authenticated and request.headers.get('Authorization'):
            from core.authentication import resolve_token_user
            from core.role_utils import get_django_user
            user = get_django_user(resolve_token_user(request))
        if user and user.is_authenticated:
            if request.path == '/app/' and request.method == 'GET':
                return redirect('operations:home')
            admin_blocked = request.path.startswith('/admin/') and not user.is_superuser
            if admin_blocked or not has_irrigation_access(user):
                if request.path == '/' and request.method == 'GET':
                    return redirect('operations:home')
                return JsonResponse({'error': '当前账号无权访问灌溉业务，请进入团队工作台。',
                                     'workspace_url': '/ops/'}, status=403)
        return self.get_response(request)
