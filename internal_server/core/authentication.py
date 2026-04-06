from rest_framework import authentication, exceptions
from .models import Worker


class TokenAuthentication(authentication.BaseAuthentication):
    """
    Custom token authentication for Worker API tokens.

    Clients authenticate by passing the token in the Authorization header:
        Authorization: Token <uuid>
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
        """
        Authenticate the worker by their API token.
        Returns (worker, token) tuple on success.
        """
        try:
            worker = Worker.objects.get(api_token=token, active=True)
        except Worker.DoesNotExist:
            raise exceptions.AuthenticationFailed('Invalid or inactive worker token.')

        if not worker.active:
            raise exceptions.AuthenticationFailed('Worker is inactive.')

        # Return the worker as the user for request.user
        return (worker, token)

    def authenticate_header(self, request):
        return self.keyword