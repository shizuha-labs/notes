"""
Custom JWT Authentication for Shizuha Notes

This authentication class validates JWT tokens issued by Shizuha ID
without requiring the user to exist in the local database.

In a microservices architecture with unified login (like Atlassian):
- Shizuha ID issues JWT tokens
- Other services (Notes, Pulse, Admin) validate and trust those tokens
- User data is fetched from the token claims, not the local database
"""

import json
import logging
import os

from rest_framework import authentication, exceptions
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)
User = get_user_model()


class FederatedUser:
    """
    A lightweight user object for federated authentication.
    Used when the user exists in Shizuha ID but not in the local database.
    """
    def __init__(self, user_id, email=None, username=None, enabled_services=None):
        self.id = user_id
        self.pk = user_id
        self.email = email or f"user_{user_id}@shizuha.id"
        self.username = username or f"user_{user_id}"
        self.is_authenticated = True
        self.is_active = True
        self.is_anonymous = False
        self.is_staff = False
        self.is_superuser = False
        # None = unrestricted (staff/superuser), [] = no services, [...] = specific services
        self.enabled_services = enabled_services

    def __str__(self):
        return f"FederatedUser({self.id})"

    def save(self, *args, **kwargs):
        pass  # No-op for federated users


# ───────────────────────── OAuth 2.0 advisory + enforcement ─────────────────
# Inlined from packages/shizuha-auth: Phase 2/4 of OAuth migration. Services
# that import the shared package should prefer that copy; this duplicate
# keeps parity while the migration to the shared package is in-flight.

def _oauth_advisory_claim_check(validated_token):
    """Log mismatched `aud`/`iss` claims without rejecting. Returns status dict."""
    import os as _os
    from django.conf import settings as _st
    service_name = getattr(_st, 'SHIZUHA_SERVICE_NAME', '') or _os.environ.get('SHIZUHA_SERVICE_NAME', '')
    expected_issuer = getattr(_st, 'SHIZUHA_EXPECTED_ISSUER', '') or _os.environ.get('SHIZUHA_EXPECTED_ISSUER', '')
    aud = validated_token.get('aud')
    if aud is not None and aud not in ('*', ['*']):
        aud_list = aud if isinstance(aud, list) else [aud]
        if service_name and service_name not in aud_list:
            logger.warning(
                f"JWT aud={aud_list!r} does not include service={service_name!r}. "
                f"Phase 2 advisory — token accepted."
            )
    iss = validated_token.get('iss')
    if iss is not None and expected_issuer and iss != expected_issuer:
        logger.warning(
            f"JWT iss={iss!r} does not match expected={expected_issuer!r}. "
            f"Phase 2 advisory — token accepted."
        )


def _oauth_enforce_audience_claim(validated_token):
    """Phase 4: when SHIZUHA_AUD_ENFORCE=True, reject tokens with mismatched aud."""
    import os as _os
    from django.conf import settings as _st
    from rest_framework_simplejwt.exceptions import InvalidToken as _InvalidToken
    enforce = bool(getattr(_st, 'SHIZUHA_AUD_ENFORCE', False)) or \
        _os.environ.get('SHIZUHA_AUD_ENFORCE', '').lower() in ('1', 'true', 'yes')
    if not enforce:
        return
    service_name = getattr(_st, 'SHIZUHA_SERVICE_NAME', '') or _os.environ.get('SHIZUHA_SERVICE_NAME', '')
    if not service_name:
        return
    aud = validated_token.get('aud')
    if aud is None or aud == '*' or aud == ['*']:
        return
    aud_list = aud if isinstance(aud, list) else [aud]
    if service_name not in aud_list:
        logger.warning(
            f"JWT rejected: aud={aud_list!r} does not include required service={service_name!r}"
        )
        raise _InvalidToken(f"Token audience {aud_list} does not include '{service_name}'")


# ───────────────────────── OAuth 2.0 RS256 validation ──────────────────────
# Phase 5 of OAuth migration: accept tokens signed with RS256 (shizuha-id's
# RSA key, public half published at /id/.well-known/jwks.json). Falls back
# from default HS256 validation so legacy tokens keep working during grace.

class _Rs256Token(dict):
    """Lightweight dict-like token — satisfies simplejwt get_user() interface."""
    pass


_JWKS_CACHE = {'keys': {}, 'fetched_at': 0}
_JWKS_TTL = 600  # seconds
_ALLOWED_JWT_ALGS = {'HS256', 'RS256'}


def _jwks_fetch_keys(force_refresh=False):
    """Fetch/cache shizuha-id JWKS keys by kid (canonical, PLAT-675 — honor kid, fail closed).

    A forced refresh (used on kid miss/rotation) returns ONLY the just-fetched key set,
    never stale keys, so an unknown kid or JWKS outage cannot validate against an old key.
    """
    import json as _json, os as _os, time as _time, urllib.request as _urlreq
    import jwt as _jwt
    if (not force_refresh and _time.time() - _JWKS_CACHE['fetched_at'] < _JWKS_TTL
            and _JWKS_CACHE['keys']):
        return _JWKS_CACHE['keys']
    issuer = (_os.environ.get('SHIZUHA_EXPECTED_ISSUER') or
              'http://shizuha-id:8001').rstrip('/')
    jwks_url = _os.environ.get('SHIZUHA_OAUTH_JWKS_URL') or f'{issuer}/.well-known/jwks.json'
    try:
        resp = _urlreq.urlopen(jwks_url, timeout=5)
        jwks = _json.loads(resp.read())
        keys = {
            k['kid']: _jwt.algorithms.RSAAlgorithm.from_jwk(_json.dumps(k))
            for k in jwks.get('keys', [])
            if k.get('kid') and k.get('kty') == 'RSA' and k.get('alg') in (None, 'RS256')
        }
        _JWKS_CACHE['keys'] = keys
        _JWKS_CACHE['fetched_at'] = _time.time()
        return keys
    except Exception as _exc:
        logger.warning(f'JWKS fetch from {jwks_url} failed: {_exc}')
        return {} if force_refresh else _JWKS_CACHE['keys']


def _try_rs256_validate(raw_token):
    """Return a _Rs256Token on success, None if not RS256, raise if bad RS256.

    Canonical (PLAT-675/PLAT-555): alg-allowlist {HS256, RS256} (reject alg=none /
    others up front — every token routes through here first), REQUIRE kid, fail
    closed on a missing/unknown key — never fall back to an arbitrary JWKS key.
    """
    import jwt as _jwt
    from rest_framework_simplejwt.exceptions import InvalidToken as _InvalidToken
    try:
        header = _jwt.get_unverified_header(raw_token)
    except Exception:
        return None
    alg = header.get('alg')
    if alg not in _ALLOWED_JWT_ALGS:
        raise _InvalidToken(f'Unsupported JWT alg={alg!r}')
    if alg != 'RS256':
        return None
    kid = header.get('kid')
    if not kid:
        raise _InvalidToken('RS256 token missing kid')
    keys = _jwks_fetch_keys()
    key = keys.get(kid)
    if key is None:
        # Re-fetch once in case of key rotation; fail closed on miss/outage.
        keys = _jwks_fetch_keys(force_refresh=True)
        key = keys.get(kid)
    if key is None:
        raise _InvalidToken(f'No JWKS key available for kid={kid!r}')
    try:
        payload = _jwt.decode(
            raw_token, key=key, algorithms=['RS256'],
            options={'verify_aud': False, 'verify_exp': True},
        )
    except _jwt.PyJWTError as exc:
        raise _InvalidToken(f'RS256 validation failed: {exc}')
    return _Rs256Token(payload)

class ShizuhaJWTAuthentication(JWTAuthentication):
    """
    Custom JWT authentication that works with Shizuha ID tokens.

    If the user doesn't exist locally, creates a FederatedUser object
    from the token claims instead of failing with 401.
    """


    def get_validated_token(self, raw_token):
        """CANONICAL JWKS verifier — keep in sync, do not fork (RS256 migration, PLAT-675).

        notes is AHEAD of the wave: RS256-PRIMARY (alg-routed) with an optional
        RS256-only mode. The canonical alg-allowlist / require-kid / fail-closed
        contract is enforced in `_try_rs256_validate`, which every token hits first.

        RS256/JWKS (OAuth, post-decoupling) is the PRIMARY validation path;
        HS256 (legacy shared-secret) is accepted only during the migration
        grace window (PLAT-352). `_try_rs256_validate` returns None for
        non-RS256 tokens (alg-based routing) and raises on a bad RS256 token."""
        tok = _try_rs256_validate(raw_token)
        if tok is None:
            # Legacy HS256 grace. Set NOTES_DISABLE_HS256=1 to enforce RS256-only
            # (the decoupled end state) — only after OIDC sign-in is live and agent
            # M2M tokens are RS256 (PLAT-356).
            import os as _os
            if _os.environ.get('NOTES_DISABLE_HS256', '').lower() in ('1', 'true', 'yes'):
                from rest_framework_simplejwt.exceptions import InvalidToken as _InvalidToken
                raise _InvalidToken('HS256 tokens rejected (RS256-only mode); sign in with Shizuha ID')
            tok = super().get_validated_token(raw_token)
        # PLAT-1036 (umbrella PLAT-1023): enforce token revocation on BOTH the RS256
        # and HS256 paths via the canonical shared client — checks
        # `iat <= access_revoked_before` through /api/oauth/revocation-status with a
        # ≤30s cache and FAILS CLOSED. Skips non-OAuth tokens (no client_id), so
        # internal/agent/legacy tokens are unaffected.
        from .token_revocation import is_token_revoked
        from rest_framework_simplejwt.exceptions import InvalidToken as _InvalidToken
        claims = tok.payload if hasattr(tok, 'payload') else tok
        raw = raw_token.decode('utf-8') if isinstance(raw_token, (bytes, bytearray)) else raw_token
        if is_token_revoked(claims, raw):
            raise _InvalidToken('Token has been revoked')
        return tok

    def get_user(self, validated_token):
        """
        Get the user from the validated token.

        CRITICAL: shizuha-id user_ids (1, 2, 3…) collide with local Django
        auto-increment PKs on each federated service's database. Doing a
        blind `User.objects.get(pk=user_id)` would hijack the federated
        identity and return whichever local user happens to sit at that
        PK (e.g. admin@example.com at local id=1 stealing every token
        whose user_id==1).

        Resolution order:
          1. Token carries an `email` claim → trust the claim, return a
             FederatedUser. This is the shizuha-id SSO happy path and
             covers the vast majority of requests.
          2. No email claim (legacy local tokens issued by this service
             itself via `/auth/token/`) → fall back to local User lookup
             by PK so Django admin logins still work.
          3. Neither → FederatedUser from whatever's in the token, with
             synthesised placeholders.
        """
        _oauth_advisory_claim_check(validated_token)
        _oauth_enforce_audience_claim(validated_token)
        user_id = validated_token.get('user_id')
        if user_id is None:
            raise InvalidToken('Token contained no recognizable user identification')

        email = validated_token.get('email')
        username = validated_token.get('username')

        # Staff/superuser override — enabled_services=None means unrestricted.
        enabled_services = validated_token.get('enabled_services')
        if validated_token.get('is_staff') or validated_token.get('is_superuser'):
            enabled_services = None

        # 1. Federated (shizuha-id) token — has an `email` claim.
        if email:
            return FederatedUser(
                user_id=user_id,
                email=email,
                username=username,
                enabled_services=enabled_services,
            )

        # 2. Legacy local token (Notes-issued via /auth/token/) — look up
        # the local Django user so Django admin session flows continue
        # working. Still safe because the PK space is consistent within
        # the same service.
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            pass

        # 3. Final fallback — federated user with placeholder claims.
        logger.debug(
            "Token user_id=%s has no email claim and no local user; "
            "returning placeholder FederatedUser",
            user_id,
        )
        return FederatedUser(
            user_id=user_id,
            email=email,
            username=username,
            enabled_services=enabled_services,
        )


class ShizuhaIDAuthentication(authentication.BaseAuthentication):
    """
    Alternative authentication that validates tokens against Shizuha ID service.

    This can be used to verify tokens by calling the Shizuha ID API directly,
    which is useful for:
    - Getting fresh user data
    - Validating token hasn't been revoked
    - Supporting token refresh flows
    """

    def authenticate(self, request):
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')

        if not auth_header.startswith('Bearer '):
            return None

        token = auth_header.split(' ')[1]

        try:
            # Validate the token locally first (fast path)
            validated_token = AccessToken(token)
            user_id = validated_token.get('user_id')

            if user_id is None:
                raise exceptions.AuthenticationFailed('Invalid token')

            # Extract enabled_services from token
            enabled_services = validated_token.get('enabled_services')
            # Staff/superuser override
            if validated_token.get('is_staff') or validated_token.get('is_superuser'):
                enabled_services = None  # None = unrestricted

            # Try local user first
            try:
                user = User.objects.get(pk=user_id)
                return (user, validated_token)
            except User.DoesNotExist:
                # Create federated user
                email = validated_token.get('email')
                username = validated_token.get('username')

                federated_user = FederatedUser(
                    user_id=user_id,
                    email=email,
                    username=username,
                    enabled_services=enabled_services
                )
                return (federated_user, validated_token)

        except TokenError as e:
            raise exceptions.AuthenticationFailed(f'Invalid token: {str(e)}')

    def authenticate_header(self, request):
        return 'Bearer realm="api"'


class FederatedTokenRefreshSerializer:
    """
    Custom token refresh serializer that proxies the refresh to Shizuha ID.

    Notes authenticates via "Sign in with Shizuha ID" (OAuth authz-code + PKCE,
    PLAT-352): the refresh token the SPA holds is a Shizuha-ID-issued RS256
    token. SimpleJWT *local* RefreshToken() cannot validate it (notes' SIMPLE_JWT
    is HS256 + local SECRET_KEY by design for non-federated flows), so a
    locally-validated refresh always 401'd on expiry and the session never
    recovered (NTS-59). Instead we forward the refresh to the ID OAuth token
    endpoint (grant_type=refresh_token) — the same issuer that minted the token —
    mirroring the confidential-client exchange in oauth_callback.
    """

    def __init__(self, data=None, **kwargs):
        self.initial_data = data or {}
        self._validated_data = None
        self._errors = None

    @property
    def validated_data(self):
        if self._validated_data is None:
            self.is_valid(raise_exception=True)
        return self._validated_data

    @property
    def errors(self):
        return self._errors or {}

    def is_valid(self, raise_exception=False):
        import urllib.error
        import urllib.parse
        import urllib.request

        from rest_framework.exceptions import ValidationError

        refresh_token = self.initial_data.get('refresh')
        if not refresh_token:
            self._errors = {'refresh': ['This field is required.']}
            if raise_exception:
                raise ValidationError(self._errors)
            return False

        client_id = (
            self.initial_data.get('client_id')
            or os.environ.get('SHIZUHA_OAUTH_CLIENT_ID', '')
        )
        token_url = (
            os.environ.get('SHIZUHA_OAUTH_TOKEN_URL')
            or os.environ.get(
                'SHIZUHA_OAUTH_ISSUER', 'http://shizuha-id:8001'
            ).rstrip('/') + '/api/oauth/token'
        )
        body = urllib.parse.urlencode({
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token,
            'client_id': client_id,
            'client_secret': os.environ.get('SHIZUHA_OAUTH_CLIENT_SECRET', ''),
        }).encode('ascii')
        req = urllib.request.Request(
            token_url,
            data=body,
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                tokens = json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read().decode())
            except Exception:  # noqa: BLE001
                detail = {}
            self._errors = {
                'refresh': [
                    detail.get('error_description') or detail.get('error')
                    or f'refresh rejected by Shizuha ID (HTTP {e.code})'
                ]
            }
            if raise_exception:
                from rest_framework_simplejwt.exceptions import InvalidToken
                raise InvalidToken(self._errors['refresh'][0])
            return False
        except Exception as exc:  # noqa: BLE001 — surface transport failures
            self._errors = {'refresh': [str(exc)]}
            if raise_exception:
                from rest_framework_simplejwt.exceptions import InvalidToken
                raise InvalidToken(str(exc))
            return False

        # Map the ID OAuth token shape ({access_token, refresh_token}) to the
        # SPA's expected {access, refresh} contract (AuthContext reads
        # response.data.refresh).
        self._validated_data = {
            'access': tokens.get('access_token', ''),
            'refresh': tokens.get('refresh_token', ''),
        }
        if not self._validated_data['access']:
            self._errors = {'refresh': ['Shizuha ID returned no access token']}
            if raise_exception:
                raise InvalidToken(self._errors['refresh'][0])
            return False
        return True


def get_federated_token_refresh_view():
    """Factory function to avoid circular imports."""
    from rest_framework.views import APIView
    from rest_framework.response import Response
    from rest_framework import status

    class FederatedTokenRefreshView(APIView):
        """
        View to refresh JWT tokens without requiring the user to exist locally.

        Takes a refresh token and returns a new access token (and optionally a new
        refresh token if rotation is enabled).
        """
        permission_classes = []
        authentication_classes = []

        def post(self, request, *args, **kwargs):
            serializer = FederatedTokenRefreshSerializer(data=request.data)

            try:
                serializer.is_valid(raise_exception=True)
                return Response(serializer.validated_data, status=status.HTTP_200_OK)
            except Exception as e:
                from rest_framework_simplejwt.exceptions import InvalidToken
                if isinstance(e, InvalidToken):
                    return Response({'detail': str(e)}, status=status.HTTP_401_UNAUTHORIZED)
                return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    return FederatedTokenRefreshView
