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

    def test_private_api_not_public(self):
        self.assertTrue(auth.is_public("/api/login"))
        self.assertFalse(auth.is_public("/api/books"))
        self.assertFalse(auth.is_public("/api/download"))

if __name__ == "__main__":
    unittest.main()
