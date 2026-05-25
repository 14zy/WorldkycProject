import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl

from config.config import BOT_TOKEN


class TelegramMiniAppAuthError(ValueError):
    pass


@dataclass(frozen=True)
class TelegramMiniAppUser:
    telegram_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    language_code: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.telegram_id,
            "username": self.username,
            "firstName": self.first_name,
            "lastName": self.last_name,
            "languageCode": self.language_code,
        }


def _decode_pairs(init_data: str) -> dict[str, str]:
    try:
        return dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError as exc:
        raise TelegramMiniAppAuthError("Invalid Telegram initData format") from exc


def _build_data_check_string(params: dict[str, str]) -> str:
    parts = [f"{key}={value}" for key, value in sorted(params.items()) if key != "hash"]
    return "\n".join(parts)


def _resolve_user(params: dict[str, str]) -> TelegramMiniAppUser:
    raw_user = params.get("user")
    if not raw_user:
        raise TelegramMiniAppAuthError("Telegram initData did not contain user payload")

    try:
        payload = json.loads(raw_user)
    except json.JSONDecodeError as exc:
        raise TelegramMiniAppAuthError("Telegram initData user payload was invalid JSON") from exc

    telegram_id = payload.get("id")
    if not isinstance(telegram_id, int):
        raise TelegramMiniAppAuthError("Telegram initData user id was missing or invalid")

    return TelegramMiniAppUser(
        telegram_id=telegram_id,
        username=payload.get("username"),
        first_name=payload.get("first_name"),
        last_name=payload.get("last_name"),
        language_code=payload.get("language_code"),
    )


def authenticate_mini_app_user(init_data: str) -> TelegramMiniAppUser:
    if not BOT_TOKEN:
        raise TelegramMiniAppAuthError("BOT_TOKEN is not configured")
    if not init_data:
        raise TelegramMiniAppAuthError("Telegram initData is required")

    params = _decode_pairs(init_data)
    provided_hash = params.get("hash")
    if not provided_hash:
        raise TelegramMiniAppAuthError("Telegram initData hash is missing")

    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    data_check_string = _build_data_check_string(params)
    expected_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_hash, provided_hash):
        raise TelegramMiniAppAuthError("Telegram initData signature is invalid")

    return _resolve_user(params)
