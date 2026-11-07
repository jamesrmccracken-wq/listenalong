"""Offline authentication contract tests for ListenAlong."""
import os
import unittest
from unittest.mock import patch

import auth


class ListenAlongAuthTests(unittest.TestCase):
    def test_production_requires_authentication(self):
        with patch.dict(os.environ, {"RENDER": "true", "APP_PASSWORD": ""}):
            self.assertTrue(auth.required())
            self.assertFalse(auth.check_password("anything"))

    def test_missing_token_rejected(self):
        self.assertFalse(auth.valid_token(None))
        self.assertFalse(auth.valid_token(""))

    def test_modified_signature_rejected(self):
        with patch.dict(os.environ, {"APP_SECRET": "test-only-secret"}):
            token = auth.sign("ok")
            self.assertTrue(auth.valid_token(token))
            self.assertFalse(auth.valid_token(token[:-1] + ("0" if token[-1] != "0" else "1")))
            self.assertFalse(auth.valid_token(auth.sign("admin")))

    def test_signed_session_expires_on_server(self):
        with patch.dict(os.environ, {"APP_SECRET": "test-only-secret"}, clear=True):
            with patch("auth.time.time", return_value=1000000000):
                token = auth.sign("ok")
                self.assertTrue(auth.valid_token(token))
            with patch("auth.time.time", return_value=1000000000 + auth.MAX_AGE):
                self.assertTrue(auth.valid_token(token))
            with patch("auth.time.time", return_value=1000000000 + auth.MAX_AGE + 1):
                self.assertFalse(auth.valid_token(token))

    def test_future_and_malformed_sessions_are_rejected(self):
        with patch.dict(os.environ, {"APP_SECRET": "test-only-secret"}, clear=True):
            with patch("auth.time.time", return_value=1000000000):
                token = auth.sign("ok")
                self.assertTrue(auth.valid_token(token))
            with patch("auth.time.time", return_value=1000000000 - 61):
                self.assertFalse(auth.valid_token(token))
            self.assertFalse(auth.valid_token(auth.sign("v1:not-a-number")))
            self.assertFalse(auth.valid_token(auth.sign("v1:9999999999999")))

    def test_legacy_static_session_is_not_accepted(self):
        with patch.dict(os.environ, {"APP_SECRET": "test-only-secret"}, clear=True):
            self.assertFalse(auth.valid_token(auth.sign("admin")))
            legacy = "ok." + __import__("hmac").new(
                auth.secret(), b"ok", __import__("hashlib").sha256
            ).hexdigest()
            self.assertFalse(auth.valid_token(legacy))

    def test_private_api_not_public(self):
        self.assertTrue(auth.is_public("/api/login"))
        self.assertFalse(auth.is_public("/api/books"))
        self.assertFalse(auth.is_public("/api/download"))

    def test_hosted_signing_secret_must_be_configured(self):
        with patch.dict(os.environ, {"RENDER": "true", "APP_SECRET": ""}):
            with self.assertRaises(RuntimeError):
                auth.secret()
        with patch.dict(os.environ, {"RENDER": "true", "APP_SECRET": "short"}):
            with self.assertRaises(RuntimeError):
                auth.secret()

    def test_hosted_strong_secret_allows_signatures(self):
        with patch.dict(os.environ, {"RENDER": "true", "APP_SECRET": "x" * 48}):
            self.assertTrue(auth.valid_token(auth.sign("ok")))

if __name__ == "__main__":
    unittest.main()
