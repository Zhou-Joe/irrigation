from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.views.static import serve

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
]

# Serve static files in development mode
if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()


# Serve media files (no nginx in this deployment). User-uploaded content (work-
# order photos, AI workspaces) lives here, so access is gated behind login — an
# anonymous visitor must not enumerate /media/work_reports/<id>/... even though
# the filenames embed predictable timestamps. `login_required` wraps Django's
# static `serve` view; login_url matches LOGIN_URL in settings.
_media_serve = login_required(serve, login_url=settings.LOGIN_URL)
urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', _media_serve, {'document_root': settings.MEDIA_ROOT}),
]
