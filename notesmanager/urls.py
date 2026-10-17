"""
URL configuration for notesmanager project (Shizuha Notes).
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)

from notes.media_serving import media_urlpatterns


def health_check(request):
    """Simple health check endpoint for container health checks."""
    return JsonResponse({'status': 'healthy'})


urlpatterns = [
    # Health check endpoint (for container healthchecks)
    path('api/health/', health_check, name='health-check'),

    # Prefixed URLs to match what nginx sends
    path('shizuha-notes/admin/', admin.site.urls),
    path('shizuha-notes/api/', include('notes.urls')),
    path('shizuha-notes/api/auth/', include('notes.auth_urls')),

    # OpenAPI schema and documentation (prefixed)
    path('shizuha-notes/api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('shizuha-notes/api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('shizuha-notes/api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    # Also keep non-prefixed URLs for direct access
    path('admin/', admin.site.urls),
    path('api/', include('notes.urls')),
    path('api/auth/', include('notes.auth_urls')),

    # OpenAPI schema and documentation (non-prefixed)
    path('api/schema/', SpectacularAPIView.as_view(), name='schema-direct'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema-direct'), name='swagger-ui-direct'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema-direct'), name='redoc-direct'),
]

# Serve static files in development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# NTS-38 #4: the unauthenticated local-media route is registered ONLY in DEBUG
# (see notes.media_serving). In production, attachments are served owner-scoped
# from object storage via /api/attachments/{pk}/file/.
urlpatterns += media_urlpatterns()
