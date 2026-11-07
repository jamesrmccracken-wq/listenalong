"""Offline authentication fail-closed regression checks."""
import os
import unittest
from unittest.mock import patch
import auth

class HostedAuthTests(unittest.TestCase):
    def test_hosted_missing_secret_rejects_tokens(self):
        with patch.dict(os.environ, {"RENDER": "true", "APP_SECRET": ""}):
            self.assertFalse(auth.valid_token("ok.deadbeef"))
            with self.assertRaises(RuntimeError):
                auth.sign("ok")

    def test_hosted_requires_password(self):
        with patch.dict(os.environ, {"RENDER": "true", "APP_PASSWORD": ""}):
            self.assertTrue(auth.required())
            self.assertFalse(auth.check_password("anything"))

    def test_signed_cookie_requires_correct_key(self):
        with patch.dict(os.environ, {"RENDER": "true", "APP_SECRET": "test-secret-123", "APP_PASSWORD": "test-password"}):
            token = auth.sign("ok")
            self.assertTrue(auth.valid_token(token))
            self.assertFalse(auth.valid_token(token + "x"))
            with patch.dict(os.environ, {"APP_SECRET": "different-secret"}):
                self.assertFalse(auth.valid_token(token))

    def test_local_passwordless_mode_is_explicit(self):
        with patch.dict(os.environ, {"APP_PASSWORD": ""}, clear=True):
            self.assertFalse(auth.required())
            self.assertTrue(auth.check_password(""))

if __name__ == "__main__":
    unittest.main()
