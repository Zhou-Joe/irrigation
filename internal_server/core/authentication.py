from rest_framework import authentication, exceptions
from django.contrib.auth import get_user_model
from .models import Worker


class TokenAuthentication(authentication.BaseAuthentication):
    """
    Custom token authentication.
    Accepts either a Worker api_token (UUID) or a User ID-based token from login.
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
        # 1. Try Worker api_token (UUID format)
        try:
            worker = Worker.objects.get(api_token=token, active=True)
            return (worker, token)
        except (Worker.DoesNotExist, Exception):
            pass

        # 2. Try User ID-based token (from login endpoint)
        try:
            user_id = int(token)
            User = get_user_model()
            user = User.objects.get(id=user_id, is_active=True)
            return (user, token)
        except (ValueError, Exception):
            pass

        raise exceptions.AuthenticationFailed('Invalid or inactive token.')

    def authenticate_header(self, request):
        return self.keyword
