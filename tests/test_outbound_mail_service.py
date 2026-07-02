import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import Mock, patch

from services.outboundMailService import _post_resend_email, build_forward_email, send_forward_email


class OutboundMailServiceTests(unittest.TestCase):
    def test_build_forward_email_sets_alias_headers_and_plain_text_body(self):
        message = build_forward_email(
            recipient_alias="VL1232",
            recipient_email="user@example.com",
            sender_header="Sender <sender@example.net>",
            subject="Original subject",
            body="To: VL1232\nFrom: Sender <sender@example.net>\nSubject: Original subject\n\nBody line",
        )

        self.assertEqual(message["From"], "VL1232@tonstealthid.com")
        self.assertEqual(message["To"], "user@example.com")
        self.assertEqual(message["Reply-To"], "Sender <sender@example.net>")
        self.assertEqual(message["Subject"], "Original subject")
        self.assertIn("Body line", message.get_body(preferencelist=("plain",)).get_content())

    @patch("services.outboundMailService.RESEND_API_KEY", "resend-test-key")
    @patch("services.outboundMailService.RESEND_BASE_URL", "https://api.resend.com")
    @patch("services.outboundMailService.RESEND_TIMEOUT_SECONDS", 15)
    @patch("services.outboundMailService.request.urlopen")
    def test_post_resend_email_builds_expected_http_request(self, urlopen: Mock):
        urlopen.return_value = Mock()

        _post_resend_email(
            {
                "from": "VL1232@tonstealthid.com",
                "to": ["user@example.com"],
                "subject": "Original subject",
                "text": "Body line\n",
                "reply_to": "Sender <sender@example.net>",
            }
        )

        req = urlopen.call_args.args[0]
        self.assertEqual(req.full_url, "https://api.resend.com/emails")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.get_header("Authorization"), "Bearer resend-test-key")
        self.assertEqual(req.get_header("Content-type"), "application/json")
        self.assertEqual(req.get_header("User-agent"), "worldkycproject-mailer/1.0")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 15)
        self.assertIn(b'"reply_to": "Sender <sender@example.net>"', req.data)

    @patch("services.outboundMailService.RESEND_API_KEY", "resend-test-key")
    @patch("services.outboundMailService.RESEND_BASE_URL", "https://api.resend.com")
    @patch("services.outboundMailService.RESEND_TIMEOUT_SECONDS", 15)
    @patch("services.outboundMailService._post_resend_email")
    def test_send_forward_email_posts_resend_payload(self, post_resend_email: Mock):
        post_resend_email.return_value = Mock()

        send_forward_email(
            recipient_alias="VL1232",
            recipient_email="user@example.com",
            sender_header="Sender <sender@example.net>",
            subject="Original subject",
            body="To: VL1232\nFrom: Sender <sender@example.net>\nSubject: Original subject\n\nBody line",
        )

        post_resend_email.assert_called_once_with(
            {
                "from": "VL1232@tonstealthid.com",
                "to": ["user@example.com"],
                "subject": "Original subject",
                "text": "To: VL1232\nFrom: Sender <sender@example.net>\nSubject: Original subject\n\nBody line\n",
                "reply_to": "Sender <sender@example.net>",
            }
        )

    @patch("services.outboundMailService.RESEND_API_KEY", "")
    def test_send_forward_email_raises_when_resend_not_configured(self):
        with self.assertRaisesRegex(RuntimeError, "Resend forwarding is not configured"):
            send_forward_email(
                recipient_alias="VL1232",
                recipient_email="user@example.com",
                sender_header="Sender <sender@example.net>",
                subject="Original subject",
                body="Body line",
            )

    @patch("services.outboundMailService.RESEND_API_KEY", "resend-test-key")
    @patch("services.outboundMailService._post_resend_email")
    def test_send_forward_email_raises_for_non_2xx_response(self, post_resend_email: Mock):
        post_resend_email.side_effect = HTTPError(
            url="https://api.resend.com/emails",
            code=422,
            msg="unprocessable",
            hdrs=None,
            fp=Mock(read=Mock(return_value=b'{"message":"invalid from"}')),
        )

        with self.assertRaisesRegex(RuntimeError, 'Resend request failed: 422 \\{"message":"invalid from"\\}'):
            send_forward_email(
                recipient_alias="VL1232",
                recipient_email="user@example.com",
                sender_header="Sender <sender@example.net>",
                subject="Original subject",
                body="Body line",
            )

    @patch("services.outboundMailService.RESEND_API_KEY", "resend-test-key")
    @patch("services.outboundMailService._post_resend_email", side_effect=URLError("network down"))
    def test_send_forward_email_raises_for_transport_error(self, _post_resend_email: Mock):
        with self.assertRaisesRegex(RuntimeError, "Resend request failed: network down"):
            send_forward_email(
                recipient_alias="VL1232",
                recipient_email="user@example.com",
                sender_header="Sender <sender@example.net>",
                subject="Original subject",
                body="Body line",
            )


if __name__ == "__main__":
    unittest.main()
