"""Canonical JWKS / RS256 verifier vectors for notes (PLAT-989 / PLAT-675).

Mirrors the canonical suite first shipped on pulse (shizuha-tasks
test_jwks_canonical_verifier.py). notes is AHEAD of the wave — its
``ShizuhaJWTAuthentication.get_validated_token`` is RS256-PRIMARY (alg-routed)
with an optional NOTES_DISABLE_HS256 RS256-only mode (PLAT-352). The canonical
alg-allowlist / require-kid / fail-closed contract is enforced in
``_try_rs256_validate`` (every token hits it first). This suite asserts:

  1. Valid HS256 token accepted          (dual-accept grace; default mode)
  2. ``alg=none`` rejected
  3. Unsupported alg (RS384) rejected     (alg-allowlist)
  4. HS256/RS256 key-confusion rejected   (RS256 payload HS256-signed w/ pubkey)
  5. Valid RS256 token (kid → JWKS) accepted
  6. Fail-closed: kid-less RS256, unknown-kid all rejected
  7. NOTES_DISABLE_HS256 → HS256 rejected (RS256-only end state)

Network is never touched — the JWKS cache is seeded directly.
"""

import base64

import hashlib

import hmac

import json

import time

import jwt

from unittest import TestCase, mock

import os

from cryptography.hazmat.primitives import serialization

from cryptography.hazmat.primitives.asymmetric import rsa

from rest_framework_simplejwt.exceptions import InvalidToken

from rest_framework_simplejwt.tokens import AccessToken

from notes import authentication as auth

KID = "test-rs256-kid"

def _make_rsa():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return priv_pem, pub_pem

def _rs256(priv_pem, *, kid=KID, alg="RS256", exp_in=3600):
    headers = {} if kid is None else {"kid": kid}
    payload = {"sub": "1", "user_id": 1, "exp": int(time.time()) + exp_in}
    return jwt.encode(payload, priv_pem, algorithm=alg, headers=headers)

def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=")

class CanonicalVerifierTests(TestCase):
    def setUp(self):
        # Signature vectors isolate cryptographic validation; the companion
        # native revocation class exercises fail-closed endpoint behavior.
        patcher = mock.patch('notes.token_revocation.is_token_revoked', return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.rsa_keys = _make_rsa()
        _, pub_pem = self.rsa_keys
        auth._JWKS_CACHE['keys'] = {KID: serialization.load_pem_public_key(pub_pem)}
        auth._JWKS_CACHE['fetched_at'] = time.time()
        self.addCleanup(auth._JWKS_CACHE.update, keys={}, fetched_at=0)

    def test_valid_hs256_accepted(self):
        raw = str(AccessToken())
        tok = auth.ShizuhaJWTAuthentication().get_validated_token(raw)
        assert tok is not None

    def test_alg_none_rejected(self):
        raw = jwt.encode({"sub": "1"}, key=None, algorithm="none")
        with self.assertRaises(InvalidToken):
            auth.ShizuhaJWTAuthentication().get_validated_token(raw)

    def test_unsupported_alg_rejected(self):
        priv_pem, _ = self.rsa_keys
        raw = _rs256(priv_pem, alg="RS384")
        with self.assertRaises(InvalidToken):
            auth.ShizuhaJWTAuthentication().get_validated_token(raw)

    def test_key_confusion_rejected(self):
        """alg=HS256 header, HMAC-signed with the RSA public-key bytes. _try_rs256_validate
        returns None for alg=HS256, so it routes to the HS256 grace path (shared
        SIGNING_KEY) where the forged signature fails."""
        _, pub_pem = self.rsa_keys
        head = _b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": KID}).encode())
        body = _b64(json.dumps({"sub": "1", "user_id": 1, "exp": int(time.time()) + 3600}).encode())
        sig = _b64(hmac.new(pub_pem, head + b"." + body, hashlib.sha256).digest())
        forged = (head + b"." + body + b"." + sig).decode()
        with self.assertRaises(InvalidToken):
            auth.ShizuhaJWTAuthentication().get_validated_token(forged)

    def test_valid_rs256_accepted(self):
        priv_pem, _ = self.rsa_keys
        raw = _rs256(priv_pem)
        tok = auth.ShizuhaJWTAuthentication().get_validated_token(raw)
        assert tok is not None
        assert tok.get("user_id") == 1

    def test_rs256_missing_kid_rejected(self):
        priv_pem, _ = self.rsa_keys
        raw = _rs256(priv_pem, kid=None)
        with self.assertRaises(InvalidToken):
            auth.ShizuhaJWTAuthentication().get_validated_token(raw)

    def test_rs256_unknown_kid_failclosed(self):
        priv_pem, _ = self.rsa_keys
        patcher = mock.patch.object(auth, "_jwks_fetch_keys", return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)
        raw = _rs256(priv_pem, kid="some-other-kid")
        with self.assertRaises(InvalidToken):
            auth.ShizuhaJWTAuthentication().get_validated_token(raw)

    def test_hs256_rejected_in_rs256_only_mode(self):
        patcher = mock.patch.dict(os.environ, {"NOTES_DISABLE_HS256":"1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        raw = str(AccessToken())  # a valid HS256 token
        with self.assertRaises(InvalidToken):
            auth.ShizuhaJWTAuthentication().get_validated_token(raw)
