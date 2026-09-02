from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from services.vmailSendService import (
    VmailConflictError,
    VmailNotFoundError,
    VmailSendError,
    VmailUnprocessableError,
    derive_compose,
    derive_reply,
    submit,
    validate_client_request_id,
)


class VmailDerivationTests(unittest.TestCase):
    def test_client_request_id_requires_exact_lowercase_hex(self):
        self.assertEqual(validate_client_request_id({"clientRequestId": "a" * 32}), "a" * 32)
        for value in ("A" * 32, "a" * 31, "g" * 32):
            with self.subTest(value=value), self.assertRaises(VmailSendError):
                validate_client_request_id({"clientRequestId": value})

    @patch("services.vmailSendService.verifiedLinkRepository.list_for_account_references")
    def test_compose_normalizes_reference_and_validates_single_recipient(self, list_links: Mock):
        list_links.return_value = [SimpleNamespace(reference="vl10776", status="Active")]

        message = derive_compose(
            "user-1",
            {
                "reference": " VL10776 ",
                "to": "recipient@example.com",
                "subject": " Hello ",
                "text": " Body ",
                "from": "attacker@example.com",
            },
        )

        self.assertEqual(message.reference, "vl10776")
        self.assertEqual(message.to_address, "recipient@example.com")
        self.assertEqual(message.subject, "Hello")
        self.assertEqual(message.text, "Body")
        list_links.assert_called_once_with("user-1", ["vl10776"])

    @patch("services.vmailSendService.verifiedLinkRepository.list_for_account_references", return_value=[])
    def test_compose_hides_missing_or_foreign_link(self, _list_links: Mock):
        with self.assertRaises(VmailNotFoundError):
            derive_compose(
                "user-1",
                {"reference": "vl2", "to": "a@example.com", "subject": "Hi", "text": "Body"},
            )

    @patch("services.vmailSendService.verifiedLinkRepository.list_for_account_references")
    def test_compose_rejects_multiple_recipients_and_header_injection(self, list_links: Mock):
        list_links.return_value = [SimpleNamespace(status="Active")]
        for recipient in ("a@example.com, b@example.com", "a@example.com\r\nBcc: b@example.com"):
            with self.subTest(recipient=recipient), self.assertRaises(VmailSendError):
                derive_compose(
                    "user-1",
                    {"reference": "vl1", "to": recipient, "subject": "Hi", "text": "Body"},
                )

    @patch("services.vmailSendService.verifiedLinkRepository.list_for_account_references")
    @patch("services.vmailSendService.outboundRepository.find_owned_inbound")
    def test_reply_derives_destination_subject_and_thread_headers(self, find_message: Mock, list_links: Mock):
        find_message.return_value = SimpleNamespace(
            id=42,
            recipient_alias="VL10776",
            reply_to="Reply Desk <reply@example.com>",
            from_header="sender@example.net",
            subject="Original subject",
            message_id="<current@example.com>",
            references="<first@example.com> <second@example.com>",
        )
        list_links.return_value = [SimpleNamespace(status="ACTIVE")]

        message = derive_reply("user-1", 42, {"text": " Answer "})

        self.assertEqual(message.to_address, "reply@example.com")
        self.assertEqual(message.subject, "Re: Original subject")
        self.assertEqual(message.in_reply_to, "<current@example.com>")
        self.assertEqual(
            message.references,
            "<first@example.com> <second@example.com> <current@example.com>",
        )

    @patch("services.vmailSendService.verifiedLinkRepository.list_for_account_references")
    @patch("services.vmailSendService.outboundRepository.find_owned_inbound")
    def test_reply_rejects_unsafe_stored_headers(self, find_message: Mock, list_links: Mock):
        find_message.return_value = SimpleNamespace(
            id=42,
            recipient_alias="vl1",
            reply_to="bad@example.com\r\nBcc: victim@example.com",
            from_header="sender@example.net",
            subject="Subject",
            message_id="42",
            references=None,
        )
        list_links.return_value = [SimpleNamespace(status="Active")]
        with self.assertRaises(VmailUnprocessableError):
            derive_reply("user-1", 42, {"text": "Answer"})


class VmailSubmissionTests(unittest.TestCase):
    def _record(self, **overrides):
        values = {
            "id": "outbound-1",
            "payload_hash": "",
            "status": "submitting",
            "from_address": "vl1@tonstealthid.com",
            "to_address": "recipient@example.com",
            "subject": "Subject",
            "body_text": "Body",
            "in_reply_to": None,
            "references": None,
            "createdAt": datetime.now(timezone.utc),
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    @patch("services.vmailSendService.outboundRepository.mark_queued")
    @patch("services.vmailSendService.send_vmail_email", return_value="resend-1")
    @patch("services.vmailSendService.outboundRepository.create_submission")
    @patch("services.vmailSendService.outboundRepository.count_recent", return_value=0)
    @patch("services.vmailSendService.outboundRepository.find_by_request", return_value=None)
    def test_first_submission_persists_then_sends_once(
        self, _find: Mock, _count: Mock, create: Mock, send: Mock, mark_queued: Mock
    ):
        from services.vmailSendService import DerivedMessage, _payload_hash

        derived = DerivedMessage("vl1", None, "recipient@example.com", "Subject", "Body")
        record = self._record(payload_hash=_payload_hash("compose", derived))
        queued = self._record(status="queued", payload_hash=record.payload_hash)
        create.return_value = (record, True)
        mark_queued.return_value = queued

        result = submit(
            user_id="user-1",
            client_request_id="a" * 32,
            kind="compose",
            derived=derived,
            correlation_id="correlation",
        )

        self.assertIs(result, queued)
        send.assert_called_once()
        self.assertTrue(send.call_args.kwargs["idempotency_key"].endswith(":" + "a" * 32))
        mark_queued.assert_called_once_with("outbound-1", "resend-1")

    @patch("services.vmailSendService.send_vmail_email")
    @patch("services.vmailSendService.outboundRepository.find_by_request")
    def test_identical_successful_replay_returns_record_without_resending(self, find: Mock, send: Mock):
        from services.vmailSendService import DerivedMessage, _payload_hash

        derived = DerivedMessage("vl1", None, "recipient@example.com", "Subject", "Body")
        record = self._record(status="queued", payload_hash=_payload_hash("compose", derived))
        find.return_value = record

        result = submit(
            user_id="user-1",
            client_request_id="a" * 32,
            kind="compose",
            derived=derived,
            correlation_id="correlation",
        )

        self.assertIs(result, record)
        send.assert_not_called()

    @patch("services.vmailSendService.outboundRepository.find_by_request")
    def test_request_id_reuse_with_changed_content_conflicts(self, find: Mock):
        from services.vmailSendService import DerivedMessage

        find.return_value = self._record(status="queued", payload_hash="different")
        with self.assertRaises(VmailConflictError):
            submit(
                user_id="user-1",
                client_request_id="a" * 32,
                kind="compose",
                derived=DerivedMessage("vl1", None, "recipient@example.com", "Subject", "Changed"),
                correlation_id="correlation",
            )


if __name__ == "__main__":
    unittest.main()
