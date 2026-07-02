from types import SimpleNamespace
import unittest
from email.message import EmailMessage
from unittest.mock import AsyncMock, Mock, call, patch

from services.mailService import (
    SYSTEM_MAILBOX_ALIAS,
    STATUS_DELIVERED,
    STATUS_PARTIAL,
    STATUS_TELEGRAM_ONLY,
    _build_plain_forward_content,
    _build_telegram_message,
    _extract_aliases,
    _process_message,
    _select_effective_aliases,
)


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

    def test_select_effective_aliases_prefers_target_alias_over_system_mailbox(self):
        self.assertEqual(_select_effective_aliases(["vl10776", "vl10488"]), ["vl10776"])

    def test_select_effective_aliases_falls_back_to_system_mailbox(self):
        self.assertEqual(_select_effective_aliases(["vl10488"]), ["vl10488"])

    def test_select_effective_aliases_keeps_multiple_target_aliases(self):
        self.assertEqual(_select_effective_aliases(["vl10776", "vl10777", "vl10488"]), ["vl10776", "vl10777"])

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

    def test_build_plain_forward_content_uses_plain_text_body(self):
        message = EmailMessage()
        message["Subject"] = "Status"
        message["From"] = "sender@example.com"
        message.set_content("Line 1\n\nLine 2")

        rendered = _build_plain_forward_content(message, "vl10488")
        self.assertTrue(
            rendered.startswith(
                "To: VL10488\nFrom: sender@example.com\nSubject: Status\n\n"
            )
        )
        self.assertIn("Line 1", rendered)


class MailIngressProcessMessageTests(unittest.IsolatedAsyncioTestCase):
    async def test_process_message_delivers_to_telegram_and_email(self):
        message = EmailMessage()
        message["Message-ID"] = "<msg-1@example.com>"
        message["To"] = "VL10776@tonstealthid.com"
        message["Delivered-To"] = "VL10488@tonstealthid.com"
        message.set_content("Body")

        with (
            patch("services.mailService.processedEmailRepository.get_by_mailbox_uid", return_value=None),
            patch("services.mailService.verifiedLinkRepository.find_by_reference", side_effect=[
                SimpleNamespace(telegramId=10776),
            ]) as find_by_reference,
            patch("services.mailService.userRepository.findUserByTelegramId", return_value=SimpleNamespace(emailAddress="user@example.com")),
            patch("services.mailService._deliver_to_telegram", new_callable=AsyncMock) as deliver_to_telegram,
            patch("services.mailService._deliver_to_user_email", new=Mock()) as deliver_to_user_email,
            patch("services.mailService.processedEmailRepository.mark_processed", new=Mock()) as mark_processed,
        ):
            await _process_message("123", message)

        find_by_reference.assert_called_once_with("vl10776")
        deliver_to_telegram.assert_awaited_once()
        deliver_to_user_email.assert_called_once_with(message, "vl10776", "user@example.com")
        self.assertEqual(deliver_to_telegram.await_args.args[0], 10776)
        mark_processed.assert_called_once_with(
            "INBOX",
            "123",
            message_id="<msg-1@example.com>",
            recipient_alias="vl10776",
            status=STATUS_DELIVERED,
            error=None,
        )

    async def test_process_message_telegram_only_when_user_email_missing(self):
        message = EmailMessage()
        message["Message-ID"] = "<msg-1b@example.com>"
        message["To"] = "VL10776@tonstealthid.com"
        message.set_content("Body")

        with (
            patch("services.mailService.processedEmailRepository.get_by_mailbox_uid", return_value=None),
            patch("services.mailService.verifiedLinkRepository.find_by_reference", return_value=SimpleNamespace(telegramId=10776)),
            patch("services.mailService.userRepository.findUserByTelegramId", return_value=SimpleNamespace(emailAddress=None)),
            patch("services.mailService._deliver_to_telegram", new_callable=AsyncMock) as deliver_to_telegram,
            patch("services.mailService._deliver_to_user_email", new=Mock()) as deliver_to_user_email,
            patch("services.mailService.processedEmailRepository.mark_processed", new=Mock()) as mark_processed,
        ):
            await _process_message("123b", message)

        deliver_to_telegram.assert_awaited_once()
        deliver_to_user_email.assert_not_called()
        mark_processed.assert_called_once_with(
            "INBOX",
            "123b",
            message_id="<msg-1b@example.com>",
            recipient_alias="vl10776",
            status=STATUS_TELEGRAM_ONLY,
            error="User email address not available",
        )

    async def test_process_message_sends_one_email_for_multiple_aliases_of_same_user(self):
        message = EmailMessage()
        message["Message-ID"] = "<msg-2@example.com>"
        message["To"] = "VL10776@tonstealthid.com"
        message["X-Original-To"] = "VL10777@tonstealthid.com"
        message["Delivered-To"] = "VL10488@tonstealthid.com"
        message.set_content("Body")

        with (
            patch("services.mailService.processedEmailRepository.get_by_mailbox_uid", return_value=None),
            patch("services.mailService.verifiedLinkRepository.find_by_reference", side_effect=[
                SimpleNamespace(telegramId=10776),
                SimpleNamespace(telegramId=10776),
            ]) as find_by_reference,
            patch("services.mailService.userRepository.findUserByTelegramId", return_value=SimpleNamespace(emailAddress="user@example.com")),
            patch("services.mailService._deliver_to_telegram", new_callable=AsyncMock) as deliver_to_telegram,
            patch("services.mailService._deliver_to_user_email", new=Mock()) as deliver_to_user_email,
            patch("services.mailService.processedEmailRepository.mark_processed", new=Mock()) as mark_processed,
        ):
            await _process_message("124", message)

        self.assertEqual(
            find_by_reference.call_args_list,
            [call("vl10776"), call("vl10777")],
        )
        self.assertEqual([args.args[0] for args in deliver_to_telegram.await_args_list], [10776])
        deliver_to_user_email.assert_called_once_with(message, "vl10776", "user@example.com")
        mark_processed.assert_called_once_with(
            "INBOX",
            "124",
            message_id="<msg-2@example.com>",
            recipient_alias="vl10776",
            status=STATUS_DELIVERED,
            error=None,
        )

    async def test_process_message_marks_partial_when_email_forwarding_fails(self):
        message = EmailMessage()
        message["Message-ID"] = "<msg-3@example.com>"
        message["To"] = "VL10776@tonstealthid.com"
        message.set_content("Body")

        with (
            patch("services.mailService.processedEmailRepository.get_by_mailbox_uid", return_value=None),
            patch("services.mailService.verifiedLinkRepository.find_by_reference", return_value=SimpleNamespace(telegramId=10776)),
            patch("services.mailService.userRepository.findUserByTelegramId", return_value=SimpleNamespace(emailAddress="user@example.com")),
            patch("services.mailService._deliver_to_telegram", new_callable=AsyncMock) as deliver_to_telegram,
            patch("services.mailService._deliver_to_user_email", side_effect=RuntimeError("smtp down")),
            patch("services.mailService.processedEmailRepository.mark_processed", new=Mock()) as mark_processed,
        ):
            await _process_message("125", message)

        deliver_to_telegram.assert_awaited_once()
        mark_processed.assert_called_once_with(
            "INBOX",
            "125",
            message_id="<msg-3@example.com>",
            recipient_alias="vl10776",
            status=STATUS_PARTIAL,
            error="smtp down",
        )


if __name__ == "__main__":
    unittest.main()
