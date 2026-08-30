from __future__ import annotations

import time
import unittest
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from utils.wkyc_assertion import WkycAssertionError, validate_wkyc_assertion


class WkycAssertionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.private_key = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        cls.public_key = private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")

    def _token(self, *, scope="vmail.read", lifetime=120, algorithm="RS256"):
        now = int(time.time())
        return jwt.encode(
            {
                "iss": "test-issuer",
                "sub": "wk-user",
                "aud": "test-audience",
                "scope": scope,
                "iat": now,
                "nbf": now,
                "exp": now + lifetime,
                "jti": "assertion-1",
            },
            self.private_key,
            algorithm=algorithm,
            headers={"kid": "test-key"},
        )

    def _configuration(self):
        return (
            patch("utils.wkyc_assertion.WKYC_ASSERTION_PUBLIC_KEYS", {"test-key": self.public_key}),
            patch("utils.wkyc_assertion.WKYC_ASSERTION_PUBLIC_KEY", None),
            patch("utils.wkyc_assertion.WKYC_ASSERTION_ISSUER", "test-issuer"),
            patch("utils.wkyc_assertion.WKYC_ASSERTION_AUDIENCE", "test-audience"),
        )

    def test_accepts_strict_rs256_assertion_with_required_scope(self):
        patches = self._configuration()
        with patches[0], patches[1], patches[2], patches[3]:
            assertion = validate_wkyc_assertion(self._token(), "vmail.read")
        self.assertEqual(assertion.user_id, "wk-user")
        self.assertEqual(assertion.jti, "assertion-1")

    def test_rejects_missing_required_scope(self):
        patches = self._configuration()
        with patches[0], patches[1], patches[2], patches[3]:
            with self.assertRaisesRegex(WkycAssertionError, "does not grant"):
                validate_wkyc_assertion(self._token(scope="vlinks.read"), "vmail.read")

    def test_rejects_assertion_lifetime_over_five_minutes(self):
        patches = self._configuration()
        with patches[0], patches[1], patches[2], patches[3]:
            with self.assertRaisesRegex(WkycAssertionError, "lifetime"):
                validate_wkyc_assertion(self._token(lifetime=301), "vmail.read")


if __name__ == "__main__":
    unittest.main()
