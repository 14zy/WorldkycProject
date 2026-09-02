from datetime import datetime, timezone
import base64
import hashlib
import hmac
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from aiohttp import web

from controller.wkycDelegatedController import (
    _assertion_from_request,
    _verify_resend_webhook,
    handle_vmail_compose,
)
from services.outboundMailService import ResendProviderError


class DelegatedSendControllerTests(unittest.IsolatedAsyncioTestCase):
    def _request(self, payload):
        return SimpleNamespace(
            headers={"Authorization": "Bearer assertion"},
            match_info={},
            json=AsyncMock(return_value=payload),
        )

    @patch("controller.wkycDelegatedController.submit_vmail")
    @patch("controller.wkycDelegatedController.derive_compose")
    @patch("controller.wkycDelegatedController._require_account", return_value=SimpleNamespace())
    @patch("controller.wkycDelegatedController._assertion_from_request")
    async def test_compose_returns_contract_and_correlation_header(
        self, assertion: Mock, _account: Mock, derive: Mock, submit: Mock
    ):
        assertion.return_value = SimpleNamespace(user_id="user-1")
        derived = SimpleNamespace(reference="vl1")
        derive.return_value = derived
        submit.return_value = SimpleNamespace(
            id="outbound-1",
            status="queued",
            createdAt=datetime(2026, 9, 2, 12, 34, 56, tzinfo=timezone.utc),
        )

        response = await handle_vmail_compose(
            self._request(
                {
                    "clientRequestId": "a" * 32,
                    "reference": "vl1",
                    "to": "recipient@example.com",
                    "subject": "Subject",
                    "text": "Body",
                }
            )
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(
            json.loads(response.body),
            {
                "message": {
                    "id": "outbound-1",
                    "status": "queued",
                    "createdAt": "2026-09-02T12:34:56Z",
                }
            },
        )
        self.assertRegex(response.headers["X-Correlation-ID"], r"^[0-9a-f]{32}$")
        submit.assert_called_once()

    @patch("controller.wkycDelegatedController.submit_vmail")
    @patch("controller.wkycDelegatedController.derive_compose", return_value=SimpleNamespace(reference="vl1"))
    @patch("controller.wkycDelegatedController._require_account", return_value=SimpleNamespace())
    @patch("controller.wkycDelegatedController._assertion_from_request")
    async def test_provider_failure_is_sanitized(
        self, assertion: Mock, _account: Mock, _derive: Mock, submit: Mock
    ):
        assertion.return_value = SimpleNamespace(user_id="user-1")
        submit.side_effect = ResendProviderError("http_503_secret", temporary=True)

        response = await handle_vmail_compose(
            self._request(
                {
                    "clientRequestId": "a" * 32,
                    "reference": "vl1",
                    "to": "recipient@example.com",
                    "subject": "Subject",
                    "text": "Body",
                }
            )
        )

        self.assertEqual(response.status, 503)
        self.assertNotIn("secret", response.text)
        self.assertIn("X-Correlation-ID", response.headers)

    @patch("controller.wkycDelegatedController.validate_wkyc_assertion")
    def test_valid_assertion_without_exact_scope_is_forbidden(self, validate: Mock):
        validate.return_value = SimpleNamespace(scopes=frozenset({"vmail.read"}))
        request = SimpleNamespace(headers={"Authorization": "Bearer assertion"})
        with self.assertRaises(web.HTTPForbidden):
            _assertion_from_request(request, "vmail.write", exact_scope=True)

    @patch("controller.wkycDelegatedController.time.time", return_value=1_700_000_000)
    @patch(
        "controller.wkycDelegatedController.RESEND_WEBHOOK_SECRET",
        "whsec_" + base64.b64encode(b"webhook-secret").decode("ascii"),
    )
    def test_resend_webhook_signature_is_verified(self, _time: Mock):
        body = b'{"type":"email.delivered"}'
        event_id = "event-1"
        timestamp = "1700000000"
        signed = f"{event_id}.{timestamp}.".encode("utf-8") + body
        signature = base64.b64encode(
            hmac.new(b"webhook-secret", signed, hashlib.sha256).digest()
        ).decode("ascii")

        verified = _verify_resend_webhook(
            body,
            {
                "svix-id": event_id,
                "svix-timestamp": timestamp,
                "svix-signature": f"v1,{signature}",
            },
        )

        self.assertEqual(verified, event_id)


if __name__ == "__main__":
    unittest.main()
