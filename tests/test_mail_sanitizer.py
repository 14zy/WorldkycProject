import unittest

from utils.mailSanitizer import chunk_telegram_text, html_to_text, sanitize_mail_text


class MailSanitizerTests(unittest.TestCase):
    def test_html_to_text_drops_script_content(self):
        value = "<div>Hello<br><script>alert(1)</script><p>World</p></div>"
        self.assertEqual(html_to_text(value).strip(), "Hello\n\nWorld")

    def test_sanitize_mail_text_removes_tracking_link_and_collapses_whitespace(self):
        value = "Hello \n\n\nhttps://example.com/?utm_source=test\n\nWorld"
        self.assertEqual(sanitize_mail_text(value), "Hello\n\nWorld")

    def test_chunk_telegram_text_splits_large_message(self):
        value = ("word " * 1200).strip()
        chunks = chunk_telegram_text(value, limit=128)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 128 for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
