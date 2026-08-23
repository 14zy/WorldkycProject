from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

from controller.tmaController import _serialize_vmail_message


class TmaVMailControllerTests(unittest.TestCase):
    def test_serialize_vmail_message_matches_blazor_contract(self):
        message = SimpleNamespace(
            id=123,
            recipient_alias="vl10776",
            from_header="Compliance Desk <review@example-bank.com>",
            reply_to="review@example-bank.com",
            subject="Additional information requested",
            receivedAt=datetime(2026, 8, 14, 3, 20, tzinfo=timezone.utc),
            processedAt=datetime(2026, 8, 14, 3, 21, tzinfo=timezone.utc),
            delivery_status="delivered",
            is_read=False,
            snippet="Please confirm the beneficiary details...",
            body_text="Please confirm the beneficiary details attached to your verified link.",
            sender_trust="anonymous",
            notary_status="N/A",
            identity_status="Not disclosed",
            governance_status="Review required",
        )

        payload = _serialize_vmail_message(message)

        self.assertEqual(payload["id"], 123)
        self.assertEqual(payload["reference"], "vl10776")
        self.assertEqual(payload["from"], "Compliance Desk <review@example-bank.com>")
        self.assertEqual(payload["replyTo"], "review@example-bank.com")
        self.assertEqual(payload["receivedAt"], "2026-08-14T03:20:00Z")
        self.assertEqual(payload["deliveryStatus"], "delivered")
        self.assertTrue(payload["isUnread"])
        self.assertEqual(payload["senderTrust"], "anonymous")
        self.assertEqual(payload["notaryStatus"], "N/A")
        self.assertEqual(payload["identityStatus"], "Not disclosed")
        self.assertEqual(payload["governanceStatus"], "Review required")


if __name__ == "__main__":
    unittest.main()
