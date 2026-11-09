"""Pilot boundary: new teams cannot reach unscoped legacy business endpoints."""
from django.conf import settings
from django.http import HttpResponseNotFound, JsonResponse
from django.shortcuts import redirect
import re


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
        if request.path.startswith(('/email-download/','/account-mail/')):
            return self.get_response(request)
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
            if (user.is_staff or user.is_superuser) and request.path.startswith(('/api/ai/','/ai/files/')):
                return self.get_response(request)
            if user.is_superuser and (request.path.startswith('/admin/') or request.path=='/profile/'):
                return self.get_response(request)
            from .access import active_membership
            from django.shortcuts import render
            member = active_membership(request) if request.user.is_authenticated else None
            selected = request.session.get('operations_business') or request.session.get('operations_membership')
            if request.user.is_authenticated and selected and not member:
                request.operations_shell = True
                if request.path == '/' and request.method == 'GET':
                    return render(request,'operations/no_membership.html',status=403)
                return JsonResponse({'error':'当前业务身份不可用，请重新选择业务。'},status=403)
            pest = member and member.team.business.code == 'pest-control'
            if pest:
                request.operations_shell = True
                if request.path == '/app/' and request.method == 'GET':
                    return redirect('core:dashboard')
                shared = {'/', '/api/zones-payload/', '/api/modal/workorder-data/',
                          '/mobile/workorder/v2/', '/work-reports/', '/work-reports/tree/new/'}
                if request.path in shared or re.fullmatch(r'/work-reports/\d+/',request.path):
                    response = self.get_response(request)
                    response['Cache-Control'] = 'private, no-store'
                    response['Vary'] = 'Cookie'
                    return response
            admin_blocked = request.path.startswith('/admin/') and not (user.is_staff or user.is_superuser)
            if admin_blocked or pest or not has_irrigation_access(user):
                if request.path == '/' and request.method == 'GET':
                    request.operations_shell = True
                    return render(request,'operations/no_membership.html',status=403)
                return JsonResponse({'error': '当前账号无权访问灌溉业务，请返回团队地图。',
                                     'workspace_url': '/ops/'}, status=403)
        return self.get_response(request)
