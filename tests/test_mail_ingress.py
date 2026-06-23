import unittest
from email.message import EmailMessage

from services.mailService import SYSTEM_MAILBOX_ALIAS, _build_telegram_message, _extract_aliases


class MailIngressTests(unittest.TestCase):
    def test_system_mailbox_alias_is_normalized_from_imap_username(self):
        self.assertEqual(SYSTEM_MAILBOX_ALIAS, "vl10488")

    def test_extract_aliases_keeps_original_recipient_when_mailbox_collects_mail(self):
        message = EmailMessage()
        message["To"] = "VL10157@tonstealthid.com"
        message["Delivered-To"] = "VL10488@tonstealthid.com"

        self.assertEqual(_extract_aliases(message), ["vl10157", "vl10488"])

    def test_extract_aliases_deduplicates_multiple_recipients(self):
        message = EmailMessage()
        message["To"] = "VL10488@tonstealthid.com, vl10488@tonstealthid.com, second@example.com"

        self.assertEqual(_extract_aliases(message), ["vl10488", "second"])

    def test_extract_aliases_combines_all_relevant_headers(self):
        message = EmailMessage()
        message["To"] = "VL10157@tonstealthid.com"
        message["X-Original-To"] = "VL10158@tonstealthid.com"
        message["Delivered-To"] = "VL10488@tonstealthid.com"

        self.assertEqual(_extract_aliases(message), ["vl10157", "vl10158", "vl10488"])

    def test_build_telegram_message_uses_plain_text_body(self):
        message = EmailMessage()
        message["Subject"] = "Status"
        message["From"] = "sender@example.com"
        message.set_content("Line 1\n\nLine 2")

        rendered = _build_telegram_message(message, "vl10488")
        self.assertTrue(
            rendered.startswith(
                "<b>To:</b> VL10488\n<b>From:</b> sender@example.com\n<b>Subject:</b> Status\n\n"
            )
        )
        self.assertIn("Line 1", rendered)

    def test_build_telegram_message_decodes_mime_subject(self):
        message = EmailMessage()
        message["Subject"] = "=?UTF-8?B?0JDQstCw0YvQstCw0YvQstC+0LDRgtGG0YPQu9Cw?="
        message["From"] = "sender@example.com"
        message.set_content("Body")

        rendered = _build_telegram_message(message, "vl10157")
        self.assertIn("<b>Subject:</b> Аваываывоатцула", rendered)


if __name__ == "__main__":
    unittest.main()
