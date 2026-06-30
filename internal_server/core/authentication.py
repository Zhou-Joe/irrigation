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
