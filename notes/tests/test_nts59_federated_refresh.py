"""
NTS-59 regression: the mid-session access-expiry/401 recovery journey.

Notes authenticates via "Sign in with Shizuha ID" (OAuth authz-code + PKCE,
PLAT-352), so the refresh token the SPA holds is Shizuha-ID-issued (RS256).
Before this fix the notes /api/auth/token/refresh/ endpoint ran the token
through SimpleJWT's LOCAL RefreshToken() (HS256 + local SECRET_KEY per the
non-federated SIMPLE_JWT settings), which can never validate an ID RS256
refresh token -> TokenError -> 401 -> the SPA's silent-refresh never recovered
and the access token stayed expired.

The fix proxies the refresh to the ID OAuth token endpoint
(grant_type=refresh_token), the same issuer that minted the token. These tests
mock that upstream exchange (both the happy path and the fail-closed path).
"""
import json
from unittest import mock

from django.test import TestCase

from notes.authentication import (
    FederatedTokenRefreshSerializer,
    get_federated_token_refresh_view,
)


class _FakeResp:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload
        self.headers = {"content-type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps(self._payload).encode()


class _FakeHTTPError(IOError):
    code = 400

    def __init__(self, payload):
        super().__init__("HTTP Error 400")
        self._payload = payload
        self.headers = {"content-type": "application/json"}

    def read(self):
        return json.dumps(self._payload).encode()


def _patch_urlopen(fn):
    return mock.patch("urllib.request.urlopen", fn)


def _post_to_view(view_cls, payload):
    """Drive a DRF APIView through full request initialization + dispatch.

    Avoids ROOT_URLCONF (test settings has none) while still exercising the
    view's request.data parsing and its status mapping. dispatch() runs its own
    initialize_request(), so we hand it the raw WSGIRequest.
    """
    from rest_framework.test import APIRequestFactory

    factory_request = APIRequestFactory().post(
        "/api/auth/token/refresh/", payload, format="json"
    )
    return view_cls().dispatch(factory_request)


class FederatedTokenRefreshRecoveryTests(TestCase):
    def test_valid_refresh_recovers_session(self):
        """A valid ID refresh token exchanges for a fresh access token (200)."""
        ok = _FakeResp(200, {
            "access_token": "new-access-jwt",
            "refresh_token": "new-refresh-jwt",
            "token_type": "Bearer",
            "expires_in": 3600,
        })
        with _patch_urlopen(lambda req, **kwargs: ok):
            ser = FederatedTokenRefreshSerializer(data={"refresh": "rs256-refresh"})
            self.assertTrue(ser.is_valid())
        # SPA contract: AuthContext reads response.data.access / .refresh
        self.assertEqual(ser.validated_data["access"], "new-access-jwt")
        self.assertEqual(ser.validated_data["refresh"], "new-refresh-jwt")

    def test_valid_refresh_via_view_returns_200(self):
        """The wired view maps a successful proxy exchange to a 200 response."""
        ok = _FakeResp(200, {
            "access_token": "view-access",
            "refresh_token": "view-refresh",
        })
        with _patch_urlopen(lambda req, **kwargs: ok):
            resp = _post_to_view(get_federated_token_refresh_view(), {"refresh": "rs256-refresh"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["access"], "view-access")

    def test_invalid_refresh_fails_closed_401(self):
        """ID rejecting the refresh (revoked/expired) -> 401, no token minted."""
        err = _FakeHTTPError({
            "error": "invalid_grant", "error_description": "token revoked",
        })
        ser = FederatedTokenRefreshSerializer(data={"refresh": "revoked"})
        with _patch_urlopen(mock.Mock(side_effect=err)):
            with self.assertRaises(Exception) as ctx:
                ser.is_valid(raise_exception=True)
        # The raised exception is SimpleJWT InvalidToken -> the view maps to 401.
        from rest_framework_simplejwt.exceptions import InvalidToken
        self.assertIsInstance(ctx.exception, InvalidToken)

    def test_invalid_refresh_via_view_returns_401(self):
        """The wired view returns 401 for an ID-rejected refresh."""
        err = _FakeHTTPError({
            "error": "invalid_grant", "error_description": "token revoked",
        })
        with _patch_urlopen(mock.Mock(side_effect=err)):
            resp = _post_to_view(get_federated_token_refresh_view(), {"refresh": "revoked"})
        self.assertEqual(resp.status_code, 401)

    def test_missing_refresh_returns_400(self):
        """No refresh token in the body -> 400 (view maps ValidationError)."""
        resp = _post_to_view(get_federated_token_refresh_view(), {})
        self.assertEqual(resp.status_code, 400)
