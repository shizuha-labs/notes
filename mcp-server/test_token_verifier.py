import asyncio
import os
import sys
import time
import unittest
from unittest import mock

import jwt

sys.path.insert(0, os.path.dirname(__file__))
from base import (  # noqa: E402
    ShizuhaTokenVerifier,
    _oauth_issuer,
    _resource_server_url,
)


class _FakeSigningKey:
    key = "rs-key"


class _FakeJwksClient:
    def __init__(self, url):
        self.url = url

    def get_signing_key_from_jwt(self, token):
        return _FakeSigningKey()


class ShizuhaTokenVerifierTests(unittest.TestCase):
    def test_default_oauth_urls_are_canonical_https(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_oauth_issuer(), "https://shizuha.com/id")
            self.assertEqual(
                _resource_server_url("notes"),
                "https://shizuha.com/mcp/notes",
            )

    def test_default_verifier_uses_canonical_https_jwks_url(self):
        token = "header.payload.signature"
        with mock.patch.dict(os.environ, {}, clear=True):
            verifier = ShizuhaTokenVerifier("notes", _oauth_issuer())
        with mock.patch("jwt.PyJWKClient", _FakeJwksClient), mock.patch(
            "base.jwt.decode",
            return_value={"user_id": 7, "exp": int(time.time()) + 3600},
        ):
            result = asyncio.run(verifier.verify_token(token))

        self.assertIsNotNone(result)
        self.assertEqual(
            verifier._jwks_client.url,
            "https://shizuha.com/id/.well-known/jwks.json",
        )

    def test_hs256_shared_secret_token_is_rejected(self):
        token = jwt.encode(
            {"user_id": 7, "exp": int(time.time()) + 3600},
            "secret",
            algorithm="HS256",
        )
        verifier = ShizuhaTokenVerifier("test", "https://id.example")

        result = asyncio.run(verifier.verify_token(token))

        self.assertIsNone(result)

    def test_rs256_jwks_token_authenticates(self):
        token = "header.payload.signature"
        verifier = ShizuhaTokenVerifier("test", "https://id.example")
        with mock.patch("jwt.PyJWKClient", _FakeJwksClient), mock.patch(
            "base.jwt.decode",
            return_value={"user_id": 7, "exp": int(time.time()) + 3600},
        ) as decode:
            result = asyncio.run(verifier.verify_token(token))

        self.assertIsNotNone(result)
        self.assertEqual(result.client_id, "7")
        decode.assert_called_once()
        self.assertEqual(decode.call_args.kwargs["algorithms"], ["RS256"])

    def test_expired_rs256_token_is_rejected_for_refresh(self):
        token = "header.payload.signature"
        verifier = ShizuhaTokenVerifier("test", "https://id.example")
        with mock.patch("jwt.PyJWKClient", _FakeJwksClient), mock.patch(
            "base.jwt.decode",
            side_effect=jwt.ExpiredSignatureError("expired"),
        ):
            result = asyncio.run(verifier.verify_token(token))

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
