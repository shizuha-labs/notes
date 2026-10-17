"""
Authentication URL configuration for Shizuha Notes.
These are proxied through to Shizuha ID, but we also include local endpoints
for token refresh and validation.
"""
from django.urls import path, include

from .oauth_views import oauth_login, oauth_callback
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenVerifyView,
)
from notes.authentication import get_federated_token_refresh_view

urlpatterns = [
    # "Sign in with Shizuha ID" (OAuth authz-code + PKCE, BFF) — PLAT-352
    path('oauth/login/', oauth_login, name='oauth-login'),
    path('oauth/callback/', oauth_callback, name='oauth-callback'),
    # JWT token endpoints
    path('token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    # Use federated token refresh that doesn't require user to exist locally
    path('token/refresh/', get_federated_token_refresh_view().as_view(), name='token_refresh'),
    path('token/verify/', TokenVerifyView.as_view(), name='token_verify'),

    # dj-rest-auth endpoints
    path('', include('dj_rest_auth.urls')),
    path('registration/', include('dj_rest_auth.registration.urls')),
]
