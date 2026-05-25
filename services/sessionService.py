import asyncio
import base64
import json
import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import data.repository.userRepository as userRepository
from api.worldKycApi import (
    extract_token_lifetime_fields,
    extract_tokens,
    refresh_authenticate,
)
from config.config import (
    WKYC_REFRESH_SCAN_INTERVAL_SECONDS,
    WKYC_REFRESH_TOKEN_DEFAULT_TTL_HOURS,
    WKYC_REFRESH_WINDOW_SECONDS,
)


logger = logging.getLogger(__name__)
AUTH_SESSION_EXPIRED_CODE = "AUTH_SESSION_EXPIRED"


class AuthSessionExpiredError(Exception):
    pass


class SessionNotLinkedError(Exception):
    pass


_refresh_locks: dict[int, asyncio.Lock] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _get_refresh_lock(telegram_id: int) -> asyncio.Lock:
    lock = _refresh_locks.get(telegram_id)
    if lock is None:
        lock = asyncio.Lock()
        _refresh_locks[telegram_id] = lock
    return lock


def _coerce_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _decode_jwt_expiry(token: str | None) -> datetime | None:
    if not token:
        return None

    parts = token.split(".")
    if len(parts) < 2:
        return None

    payload_part = parts[1]
    payload_part += "=" * (-len(payload_part) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_part.encode("ascii")))
    except (ValueError, UnicodeDecodeError):
        return None

    exp = payload.get("exp")
    if not isinstance(exp, int):
        return None
    return datetime.fromtimestamp(exp, tz=timezone.utc)


def build_token_metadata(payload: dict[str, Any], *, now: datetime | None = None) -> dict[str, datetime | None]:
    issued_at = now or _utcnow()
    access_token, _refresh_token = extract_tokens(payload)
    _access_minutes, refresh_hours = extract_token_lifetime_fields(payload)
    access_expiry = _decode_jwt_expiry(access_token)

    refresh_expiry = None
    if isinstance(refresh_hours, int) and refresh_hours > 0:
        refresh_expiry = issued_at + timedelta(hours=refresh_hours)
    elif isinstance(refresh_hours, float) and refresh_hours > 0:
        refresh_expiry = issued_at + timedelta(hours=refresh_hours)
    else:
        refresh_expiry = issued_at + timedelta(hours=WKYC_REFRESH_TOKEN_DEFAULT_TTL_HOURS)

    return {
        "accessTokenExpiresAt": access_expiry,
        "refreshTokenExpiresAt": refresh_expiry,
        "lastTokenRefreshAt": issued_at,
    }


def _needs_refresh(user, *, now: datetime | None = None) -> bool:
    current_time = now or _utcnow()
    access_expiry = _coerce_datetime(getattr(user, "accessTokenExpiresAt", None))
    if access_expiry is None:
        return True
    return access_expiry <= current_time + timedelta(seconds=WKYC_REFRESH_WINDOW_SECONDS)


def _refresh_expired(user, *, now: datetime | None = None) -> bool:
    current_time = now or _utcnow()
    refresh_expiry = _coerce_datetime(getattr(user, "refreshTokenExpiresAt", None))
    if refresh_expiry is None:
        return False
    return refresh_expiry <= current_time


def _is_refresh_failure(status_code: int | None, message: str | None) -> bool:
    if status_code in (400, 401, 403):
        return True
    if not message:
        return False
    normalized = message.lower()
    return any(fragment in normalized for fragment in ("expired", "invalid", "unauthorized", "forbidden"))


def _persist_tokens(telegram_id: int, user_id: str, access_token: str, refresh_token: str, payload: dict[str, Any]):
    metadata = build_token_metadata(payload)
    userRepository.saveUser(
        telegram_id,
        user_id,
        access_token,
        refresh_token,
        metadata["accessTokenExpiresAt"],
        metadata["refreshTokenExpiresAt"],
        metadata["lastTokenRefreshAt"],
    )
    return metadata


def _refresh_retry_needed(result: dict[str, Any]) -> bool:
    return result.get("ok") is False and result.get("status_code") == 401


def store_login_session(telegram_id: int, user_id: str, payload: dict[str, Any]):
    access_token, refresh_token = extract_tokens(payload)
    if not access_token or not refresh_token:
        raise ValueError("Expected access token and refresh token in payload")
    return _persist_tokens(telegram_id, user_id, access_token, refresh_token, payload)


async def _refresh_user_session(telegram_id: int, force: bool = False):
    lock = _get_refresh_lock(telegram_id)
    async with lock:
        user = userRepository.findUserByTelegramId(telegram_id)
        if not user or not user.accessToken or not user.refreshToken:
            raise SessionNotLinkedError()

        if _refresh_expired(user):
            userRepository.clearUserTokens(telegram_id)
            raise AuthSessionExpiredError()

        if not force and not _needs_refresh(user):
            return userRepository.findUserByTelegramId(telegram_id)

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: refresh_authenticate(user.accessToken, user.refreshToken),
        )
        if not result.get("ok"):
            if _is_refresh_failure(result.get("status_code"), result.get("message")):
                userRepository.clearUserTokens(telegram_id)
                raise AuthSessionExpiredError()
            raise RuntimeError(result.get("message", "Failed to refresh session"))

        payload = result.get("payload") or {}
        access_token, refresh_token = extract_tokens(payload)
        if not access_token:
            raise RuntimeError("Refresh response did not include access token")
        if not refresh_token:
            refresh_token = user.refreshToken

        metadata = build_token_metadata(payload)
        userRepository.updateUserTokens(
            telegram_id,
            access_token,
            refresh_token,
            metadata["accessTokenExpiresAt"],
            metadata["refreshTokenExpiresAt"],
            metadata["lastTokenRefreshAt"],
        )
        logger.info("Refreshed WorldKyc session for telegramId=%s", telegram_id)
        return userRepository.findUserByTelegramId(telegram_id)


async def ensure_valid_access_token(telegram_id: int) -> str:
    user = userRepository.findUserByTelegramId(telegram_id)
    if not user or not user.accessToken or not user.refreshToken:
        raise SessionNotLinkedError()

    if _refresh_expired(user):
        userRepository.clearUserTokens(telegram_id)
        raise AuthSessionExpiredError()

    if _needs_refresh(user):
        user = await _refresh_user_session(telegram_id)

    if not user or not user.accessToken:
        raise AuthSessionExpiredError()
    return user.accessToken


async def resolve_link_state(telegram_id: int) -> tuple[Any, bool]:
    user = userRepository.findUserByTelegramId(telegram_id)
    if not user or not user.accessToken or not user.refreshToken:
        return user, False

    try:
        await ensure_valid_access_token(telegram_id)
    except SessionNotLinkedError:
        return None, False
    except AuthSessionExpiredError:
        return None, False
    except RuntimeError:
        return userRepository.findUserByTelegramId(telegram_id), True

    refreshed_user = userRepository.findUserByTelegramId(telegram_id)
    return refreshed_user, bool(refreshed_user and refreshed_user.accessToken)


async def call_with_valid_session(
    telegram_id: int,
    api_call: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    token = await ensure_valid_access_token(telegram_id)
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, lambda: api_call(token))
    if not _refresh_retry_needed(result):
        return result

    user = await _refresh_user_session(telegram_id, force=True)
    if not user or not user.accessToken:
        raise AuthSessionExpiredError()

    retry_result = await loop.run_in_executor(None, lambda: api_call(user.accessToken))
    return retry_result


async def refresh_sessions_loop():
    while True:
        try:
            users = userRepository.findLinkedUsers()
            for user in users:
                if not user or not user.telegramId:
                    continue
                if _refresh_expired(user):
                    userRepository.clearUserTokens(user.telegramId)
                    continue
                if not _needs_refresh(user):
                    continue
                try:
                    await _refresh_user_session(user.telegramId)
                except AuthSessionExpiredError:
                    logger.info("WorldKyc session expired during background refresh telegramId=%s", user.telegramId)
                except RuntimeError as exc:
                    logger.warning(
                        "Background session refresh failed for telegramId=%s: %s",
                        user.telegramId,
                        exc,
                    )
        except Exception:
            logger.exception("Background WorldKyc refresh loop failed")

        await asyncio.sleep(WKYC_REFRESH_SCAN_INTERVAL_SECONDS)
