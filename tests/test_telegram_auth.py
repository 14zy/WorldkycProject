from __future__ import annotations

import hashlib
import hmac
import json
import unittest
from urllib.parse import urlencode
from unittest.mock import patch

from utils.telegram_mini_app import TelegramMiniAppAuthError, authenticate_mini_app_user


def _signed_init_data(bot_token: str, auth_date: int) -> str:
    params = {
        "auth_date": str(auth_date),
        "query_id": "test-query",
        "user": json.dumps({"id": 12345, "first_name": "Test"}, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    params["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(params)


class TelegramMiniAppAuthTests(unittest.TestCase):
    def test_accepts_recent_signed_init_data(self):
        token = "test-bot-token"
        with patch("utils.telegram_mini_app.BOT_TOKEN", token):
            user = authenticate_mini_app_user(_signed_init_data(token, 1_000), now=1_100)
        self.assertEqual(user.telegram_id, 12345)

    def test_rejects_stale_signed_init_data(self):
        token = "test-bot-token"
        with patch("utils.telegram_mini_app.BOT_TOKEN", token):
            with self.assertRaisesRegex(TelegramMiniAppAuthError, "expired"):
                authenticate_mini_app_user(_signed_init_data(token, 1_000), now=5_000)

    def test_rejects_future_signed_init_data(self):
        token = "test-bot-token"
        with patch("utils.telegram_mini_app.BOT_TOKEN", token):
            with self.assertRaisesRegex(TelegramMiniAppAuthError, "future"):
                authenticate_mini_app_user(_signed_init_data(token, 2_000), now=1_000)


if __name__ == "__main__":
    unittest.main()
