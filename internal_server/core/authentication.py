from rest_framework import authentication, exceptions
from .models import Worker, ManagerProfile, DepartmentUserProfile


class TokenAuthentication(authentication.BaseAuthentication):
    """
    Custom token authentication.
    Accepts UUID api_tokens from Worker, ManagerProfile, or DepartmentUserProfile.
    """
    keyword = 'Token'

    def authenticate(self, request):
        auth = authentication.get_authorization_header(request).split()

        if not auth or auth[0].lower() != self.keyword.lower().encode():
            return None

        if len(auth) == 1:
            raise exceptions.AuthenticationFailed('Invalid token header. No credentials provided.')
        elif len(auth) > 2:
            raise exceptions.AuthenticationFailed('Invalid token header. Token string should not contain spaces.')

        try:
            token = auth[1].decode()
        except UnicodeError:
            raise exceptions.AuthenticationFailed('Invalid token header. Token string should not contain invalid characters.')

        return self.authenticate_credentials(token)

    def authenticate_credentials(self, token):
        # 1. Try Worker api_token
        try:
            worker = Worker.objects.get(api_token=token, active=True)
            return (worker, token)
        except (Worker.DoesNotExist, Exception):
            pass

        # 2. Try ManagerProfile api_token
        try:
            manager = ManagerProfile.objects.get(api_token=token, active=True)
            return (manager, token)
        except (ManagerProfile.DoesNotExist, Exception):
            pass

        # 3. Try DepartmentUserProfile api_token
        try:
            dept_user = DepartmentUserProfile.objects.get(api_token=token, active=True)
            return (dept_user, token)
        except (DepartmentUserProfile.DoesNotExist, Exception):
            pass

        # NOTE: a numeric user-ID fallback was removed — it let any caller forge
        # `Authorization: Token 1` to impersonate a superuser (low/PK-guessable).
        # Admins authenticate via a real ManagerProfile.api_token instead.

        raise exceptions.AuthenticationFailed('Invalid or inactive token.')

    def authenticate_header(self, request):
        return self.keyword


# Singleton instance reused by ``token_or_session`` below and by callers that
# want to resolve a token without going through DRF's request pipeline.
_token_auth = TokenAuthentication()


def resolve_token_user(request):
    """Resolve a user from an ``Authorization: Token <uuid>`` header.

    Returns the authenticated user (Django ``User`` *or* a profile model —
    Worker / ManagerProfile / DepartmentUserProfile) on success, or ``None``
    if the header is absent / invalid. Raises never — a bad token just yields
    ``None`` so the caller's existing ``@login_required`` gate decides the
    response (302 redirect for browser nav, or a downstream 403).

    This lets the many ``@login_required`` views accept token auth WITHOUT
    rewriting each as a DRF function view: stack ``@token_or_session`` above
    ``@login_required`` and a token caller gets ``request.user`` populated just
    like a session caller would.
    """
    auth = authentication.get_authorization_header(request).split()
    if not auth or auth[0].lower() != b'token':
        return None
    if len(auth) != 2:
        return None
    try:
        token = auth[1].decode()
    except UnicodeError:
        return None
    try:
        user, _tok = _token_auth.authenticate_credentials(token)
        return user
    except exceptions.AuthenticationFailed:
        return None


def token_or_session(view_func=None, *, require_manager=False):
    """Decorator: populate ``request.user`` from a token header if present,
    then defer to the view's own ``@login_required`` gate.

    Designed to sit ABOVE ``@login_required`` (OUTERMOST) so that it resolves the
    token and populates ``request.user`` BEFORE login_required checks it.
    Decorators apply bottom-up, so the topmost decorator's wrapper runs first on
    the incoming request::

        @token_or_session
        @login_required(login_url='core:login')
        def my_api(request): ...

        # Restrict token access to manager / super-admin only (field workers and
        # dept users keep session access in the browser, but their tokens can't
        # call this API):
        @token_or_session(require_manager=True)
        @login_required(login_url='core:login')
        def sensitive_api(request): ...

    - No ``Authorization`` header → nothing changes; session auth proceeds as
      before (browser AJAX, admin dashboard).
    - Valid token header → ``request.user`` is set to the resolved profile/
      Django-user, so ``@login_required`` sees an authenticated user and the
      view body runs unchanged. When ``require_manager=True``, only tokens
      belonging to a ManagerProfile (admin/manager) are honored; Worker /
      DepartmentUserProfile tokens are refused so field-worker / dept-user
      tokens can't reach these data APIs. The mobile app still authenticates
      fine via the global DRF ``TokenAuthentication`` on the ViewSets — this
      gate applies only to the decorated function views.
    - Invalid token header → ``request.user`` stays anonymous, and
      ``@login_required`` returns its 302-to-login as usual.

    DRF raises ``AuthenticationFailed`` on a bad token; we swallow it so a bad
    token is treated identically to "no token" (the login_required gate then
    rejects). This matches how DRF's SessionAuthentication behaves when no
    session is present.
    """
    from functools import wraps

    def _decorate(func):
        @wraps(func)
        def _wrapper(request, *args, **kwargs):
            # Session already authenticated (browser) → pass through regardless
            # of require_manager: the browser session path keeps its current
            # behavior (any logged-in role can use the page's own AJAX).
            if getattr(request.user, 'is_authenticated', False):
                return func(request, *args, **kwargs)
            # Token path: resolve, then optionally restrict to manager role.
            user = resolve_token_user(request)
            if user is not None:
                if require_manager and not isinstance(user, ManagerProfile):
                    # A Worker / DepartmentUserProfile token on a manager-only
                    # endpoint → return a clean 403 JSON for API callers, or
                    # fall through anonymous (→ login_required 302) for a
                    # browser navigation. JsonResponse (not DRF Response)
                    # because these views aren't @api_view and have no renderer.
                    accept = request.META.get('HTTP_ACCEPT', '')
                    is_api = ('application/json' in accept
                              or request.headers.get('X-Requested-With') == 'XMLHttpRequest')
                    if is_api:
                        from django.http import JsonResponse
                        return JsonResponse(
                            {'error': '此 API 仅限管理员/经理 token 访问'}, status=403)
                    # Non-AJAX: leave anonymous so login_required redirects.
                else:
                    request.user = user
            return func(request, *args, **kwargs)
        return _wrapper

    # Allow both @token_or_session and @token_or_session(require_manager=True).
    if view_func is not None:
        return _decorate(view_func)
    return _decorate
