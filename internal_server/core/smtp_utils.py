"""SMTP connection helpers — prefer the UI-configured DB setting, fall back to env.

The 邮件报表 tab lets a manager configure SMTP (host/port/credentials) without
touching server env vars. These helpers centralize the resolution so both the
scheduled command (send_report_email) and the interactive test-send view build
their EmailMessage with the same connection source:

  1. EmailSmtpSetting.get_solo() — if it has a host, use it (DB wins).
  2. Otherwise fall through to Django's settings.EMAIL_* (env vars).

Keeping this in one place means the SMTP gate check and the actual send always
agree on whether SMTP is configured and which server they target.
"""
from django.conf import settings
from django.core.mail import get_connection


def smtp_solo():
    """Return the singleton EmailSmtpSetting row (never raises)."""
    from core.models import EmailSmtpSetting
    return EmailSmtpSetting.get_solo()


def is_smtp_configured():
    """True if SMTP is usable — either the DB row has a host OR EMAIL_HOST env is set."""
    if smtp_solo().is_configured:
        return True
    return bool(getattr(settings, 'EMAIL_HOST', ''))


def get_email_connection():
    """Build an SMTP backend connection from DB config, falling back to env.

    Returns a live (unopened) EmailBackend; EmailMessage.send(connection=...)
    opens it lazily and closes it after sending.
    """
    s = smtp_solo()
    if s.is_configured:
        return get_connection(
            host=s.host,
            port=s.port,
            username=s.username or None,
            password=s.password or None,
            use_ssl=s.use_ssl,
            use_tls=s.use_tls,
            timeout=getattr(settings, 'EMAIL_TIMEOUT', 30),
        )
    # Fall back to environment-configured settings.EMAIL_*.
    return get_connection()


def resolve_from_email():
    """The From address: DB from_email → DB username → settings.DEFAULT_FROM_EMAIL."""
    s = smtp_solo()
    if s.is_configured:
        return s.from_email or s.username or getattr(settings, 'DEFAULT_FROM_EMAIL', '')
    return getattr(settings, 'DEFAULT_FROM_EMAIL', '')
