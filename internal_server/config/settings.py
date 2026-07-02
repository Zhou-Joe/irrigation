import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# SECRET_KEY must be provided via the environment — a leaked key lets an attacker
# forge session cookies / CSRF / password-reset tokens (full auth bypass). The old
# hardcoded default has been removed and must be rotated. In DEBUG mode we tolerate a
# throwaway generated key so local dev still boots; production refuses to start without one.
DEBUG = os.environ.get('DEBUG', 'False') == 'True'
_secret = os.environ.get('SECRET_KEY')
if _secret:
    SECRET_KEY = _secret
elif DEBUG:
    import secrets as _secrets
    SECRET_KEY = 'dev-only-' + _secrets.token_urlsafe(50)
else:
    raise RuntimeError(
        'SECRET_KEY environment variable is required in production. '
        'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(50))"'
    )
ALLOWED_HOSTS = os.environ.get(
    'ALLOWED_HOSTS',
    'localhost,127.0.0.1,zctestbench.asia,www.zctestbench.asia,irrigation.zctestbench.asia,192.168.137.2'
).split(',')
# Note: the previous default included the ephemeral `.trycloudflare.com` wildcard and
# hardcoded LAN/public IPs — the wildcard let anyone Host-spoof via a free Quick
# Tunnel, and the IPs leaked topology. Override via the env var if a specific
# temporary host or IP is genuinely needed.

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'core.apps.CoreConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    # GZip must come before any middleware that reads/writes the response body. The
    # dashboard ships ~6MB of inline JSON; without compression every byte crosses the
    # cloud tunnel uncompressed (the root cause of the 50s+ load time). This alone takes
    # the page from ~6MB to ~1MB on the wire.
    'django.middleware.gzip.GZipMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'core' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.notifications',
                'core.context_processors.user_role',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

# Allow large DXF uploads (default Django limit is 2.5MB → "request entity too large").
DATA_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024       # 100 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024       # 100 MB


MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Security settings
if not DEBUG:
    # Cookie flags were previously forced False here (a bug) — they must be True in
    # production so session/CSRF cookies are only ever sent over HTTPS.
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    # Ali Cloud nginx terminates TLS and forwards to FRP tunnel over HTTP. It does
    # NOT send X-Forwarded-Proto, so Django sees every request as HTTP — and a
    # SECURE_SSL_REDIRECT here loops forever (browser hits HTTPS → nginx → HTTP →
    # Django issues 301 → HTTPS → nginx → HTTP → …). The nginx layer already
    # redirects HTTP→HTTPS at the edge, so Django's redirect is redundant.
    # To re-enable, ensure the proxy sends X-Forwarded-Proto: https.
    # SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Login settings
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'

# CORS settings
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = [
    'https://zctestbench.asia',
    'https://www.zctestbench.asia',
    'https://irrigation.zctestbench.asia',
    'http://localhost:5001',
    'http://localhost:5000',
    'http://127.0.0.1:5001',
    'http://127.0.0.1:5000',
]
CORS_ALLOWED_ORIGIN_REGEXES = [
    r'^https?://(.*\.)?zctestbench\.asia$',
    r'^https?://localhost:\d+$',
    r'^https?://127\.0\.0\.1:\d+$',
]

# CSRF trusted origins for Django 4+ — HTTPS hostnames only. The previous list
# included a bare http:// public IP which undermined HTTPS-based CSRF protection.
CSRF_TRUSTED_ORIGINS = [
    'https://zctestbench.asia',
    'https://www.zctestbench.asia',
    'https://irrigation.zctestbench.asia',
]

# Cloud Relay settings
CLOUD_RELAY_BASE_URL = os.environ.get('CLOUD_RELAY_BASE_URL', 'https://horticulture-relay.your-domain.workers.dev')
CLOUD_RELAY_POLL_TOKEN = os.environ.get('CLOUD_RELAY_POLL_TOKEN', None)
