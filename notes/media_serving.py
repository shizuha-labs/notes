"""Local media serving for Shizuha Notes (NTS-38 #4).

Kept in the `notes` app (a dependency-light module) so the DEBUG-gate and the
path-traversal containment are unit-testable without importing the full project
urlconf (which pulls in admin/drf-spectacular/celery).

In PRODUCTION attachments live in object storage (MinIO/S3) and are served
owner-scoped via `/api/attachments/{pk}/file/`; the unauthenticated local-media
route below is registered ONLY when `settings.DEBUG` is true, so a non-MinIO
deploy can't leak any MEDIA_ROOT file by guessable path with no auth.
"""
import mimetypes
import os

from django.conf import settings
from django.http import FileResponse, Http404
from django.urls import re_path

# MEDIA_URL is '/shizuha-notes/media/'.
_MEDIA_ROUTE = r'^shizuha-notes/media/(?P<path>.*)$'


def serve_media(request, path):
    """Serve a local media file in DEBUG/development only.

    Contains resolution within MEDIA_ROOT so a `../` traversal path can't read
    files outside the media directory."""
    media_root = os.path.realpath(settings.MEDIA_ROOT)
    file_path = os.path.realpath(os.path.join(media_root, path))
    if file_path != media_root and not file_path.startswith(media_root + os.sep):
        raise Http404("File not found")
    if os.path.exists(file_path) and os.path.isfile(file_path):
        content_type, _ = mimetypes.guess_type(file_path)
        return FileResponse(
            open(file_path, 'rb'),
            content_type=content_type or 'application/octet-stream',
        )
    raise Http404("File not found")


def media_urlpatterns():
    """The unauthenticated local-media route — present ONLY in DEBUG (NTS-38 #4)."""
    if settings.DEBUG:
        return [re_path(_MEDIA_ROUTE, serve_media, name='serve_media')]
    return []
