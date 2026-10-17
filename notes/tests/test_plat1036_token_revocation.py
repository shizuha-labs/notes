"""PLAT-1036 (umbrella PLAT-1023): notes RS256 verifier enforces token revocation.

`ShizuhaJWTAuthentication.get_validated_token` must reject a validly-signed but
REVOKED OAuth token via the canonical shared client
(`notes.token_revocation.is_token_revoked` — `iat <= access_revoked_before` via
`/api/oauth/revocation-status`, ≤30s cache, FAIL CLOSED). Tokens without `client_id` are also checked (SCLI-376). The check sits after both the RS256 and HS256
validation paths converge, so it applies to both.

Pure unit — no DB, no network (requests is mocked).
"""
from unittest import mock

from unittest import TestCase
from rest_framework_simplejwt.exceptions import InvalidToken

from notes import authentication as auth
from notes import token_revocation


def _validated(client_id="cli-1"):
    """Shape `_try_rs256_validate` returns — a dict-like validated token."""
    t = {"user_id": 1, "email": "u@example.com"}
    if client_id is not None:
        t["client_id"] = client_id
    return t



class TokenRevocationTests(TestCase):
    def setUp(self):
        token_revocation._REVOCATION_CACHE.clear()
        self.addCleanup(token_revocation._REVOCATION_CACHE.clear)

    def test_revoked_oauth_token_rejected(self):
        tok = _validated()
        with mock.patch.object(auth, "_try_rs256_validate", return_value=tok), \
             mock.patch.object(token_revocation, "is_token_revoked", return_value=True) as rev:
            with self.assertRaises(InvalidToken):
                auth.ShizuhaJWTAuthentication().get_validated_token("raw.jwt.token")
        rev.assert_called_once()

    def test_active_oauth_token_passes(self):
        tok = _validated()
        with mock.patch.object(auth, "_try_rs256_validate", return_value=tok), \
             mock.patch.object(token_revocation, "is_token_revoked", return_value=False):
            assert auth.ShizuhaJWTAuthentication().get_validated_token("raw.jwt.token") is tok

    def test_fail_closed_on_lookup_error(self):
        """Real is_token_revoked + revocation endpoint raising → treated revoked → rejected."""
        tok = _validated()
        with mock.patch.object(auth, "_try_rs256_validate", return_value=tok), \
             mock.patch.object(token_revocation.requests, "post", side_effect=Exception("boom")):
            with self.assertRaises(InvalidToken):
                auth.ShizuhaJWTAuthentication().get_validated_token("raw.jwt.token")

    def test_active_endpoint_response_allows(self):
        """Real is_token_revoked + endpoint {active:true} → not revoked → passes."""
        tok = _validated()
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {"active": True}
        with mock.patch.object(auth, "_try_rs256_validate", return_value=tok), \
             mock.patch.object(token_revocation.requests, "post", return_value=resp):
            assert auth.ShizuhaJWTAuthentication().get_validated_token("raw.jwt.token") is tok

    def test_revoked_endpoint_response_rejected(self):
        """Real is_token_revoked + endpoint {active:false} → revoked → rejected."""
        tok = _validated()
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {"active": False}
        with mock.patch.object(auth, "_try_rs256_validate", return_value=tok), \
             mock.patch.object(token_revocation.requests, "post", return_value=resp):
            with self.assertRaises(InvalidToken):
                auth.ShizuhaJWTAuthentication().get_validated_token("raw.jwt.token")

    def test_non_oauth_token_requires_active_revocation_response(self):
        """Session/agent tokens without client_id are tracked by native ID too."""
        tok = _validated(client_id=None)
        response = mock.Mock(status_code=200)
        response.json.return_value = {"active":True}
        with mock.patch.object(auth, "_try_rs256_validate", return_value=tok), \
             mock.patch.object(token_revocation.requests, "post", return_value=response) as lookup:
            self.assertIs(auth.ShizuhaJWTAuthentication().get_validated_token("raw.jwt.token"),tok)
        lookup.assert_called_once()

    def test_non_oauth_revoked_token_is_rejected(self):
        tok = _validated(client_id=None)
        response = mock.Mock(status_code=200)
        response.json.return_value = {"active":False}
        with mock.patch.object(auth, "_try_rs256_validate", return_value=tok), \
             mock.patch.object(token_revocation.requests, "post", return_value=response):
            with self.assertRaises(InvalidToken):
                auth.ShizuhaJWTAuthentication().get_validated_token("raw.jwt.token")
