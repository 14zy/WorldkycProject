from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web

import data.repository.userRepository as userRepository
import data.repository.verifiedLinkRepository as verifiedLinkRepository
import data.repository.vmailMessageRepository as vmailMessageRepository
import data.repository.telegramLinkRepository as telegramLinkRepository
import data.repository.telegramConnectionCodeRepository as telegramConnectionCodeRepository
import data.repository.worldKycAccountRepository as worldKycAccountRepository
from api.worldKycApi import (
    authenticate,
    extract_tokens,
    extract_user_id,
)
from config.config import WKYC_TELEGRAM_CONNECT_URL, WKYC_VLINK_BASE_URL
from services.sessionService import (
    AuthSessionExpiredError,
    SessionNotLinkedError,
    store_login_session,
)
from services.vlinkSyncService import sync_user_vlinks
from utils.telegram_mini_app import TelegramMiniAppAuthError, authenticate_mini_app_user


logger = logging.getLogger(__name__)

FRONTEND_DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"
FRONTEND_ASSETS_DIR = FRONTEND_DIST_DIR / "assets"


def register_tma_routes(app: web.Application):
    app.router.add_post("/api/tma/bootstrap", handle_bootstrap)
    app.router.add_post("/api/tma/login", handle_login)
    app.router.add_post("/api/tma/logout", handle_logout)
    app.router.add_post("/api/tma/connect/code", handle_connection_code)
    app.router.add_get("/api/tma/vlinks", handle_vlinks)
    app.router.add_get("/api/tma/vmail/messages", handle_vmail_messages)
    app.router.add_post("/api/tma/vmail/messages/{id}/read", handle_vmail_message_read)
    app.router.add_get("/tma/assets/{tail:.*}", handle_tma_asset)
    app.router.add_get("/tma", handle_tma_index)
    app.router.add_get("/tma/{tail:.*}", handle_tma_index)


def _json_error(message: str, status: int, *, details=None):
    payload = {"error": message}
    if details is not None:
        payload["details"] = details
    return web.json_response(payload, status=status)


def _build_upstream_error(result):
    details = result.get("details")
    if isinstance(details, dict) and details:
        payload = {"error": result.get("message", "Upstream API error"), "details": details}
    elif details:
        payload = {"error": result.get("message", "Upstream API error"), "details": str(details)}
    else:
        payload = {"error": result.get("message", "Upstream API error")}

    return web.json_response(payload, status=result.get("status_code", 502))


def _mask_login_id(login_id: str | None) -> str:
    if not login_id:
        return "<empty>"
    if len(login_id) <= 4:
        return "*" * len(login_id)
    return f"{login_id[:2]}***{login_id[-2:]}"


def _split_references(raw_references: str | None) -> list[str]:
    if not raw_references:
        return []
    return [reference.strip().casefold() for reference in raw_references.split(",") if reference.strip()]


def _parse_int_query(request: web.Request, name: str, default: int, minimum: int, maximum: int) -> int:
    raw_value = request.query.get(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise web.HTTPBadRequest(
            text=web.json_response({"error": f"{name} must be an integer"}).text,
            content_type="application/json",
        ) from exc
    return max(minimum, min(value, maximum))


def _parse_bool_query(request: web.Request, name: str, default: bool = False) -> bool:
    raw_value = request.query.get(name)
    if raw_value is None:
        return default
    return raw_value.strip().casefold() in {"1", "true", "yes", "on"}


def _isoformat_utc(value):
    if not value:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _received_label(value) -> str:
    if not value:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - value.astimezone(timezone.utc)
    seconds = max(0, int(delta.total_seconds()))
    if seconds < 60:
        return "Just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 30:
        return f"{days}d ago"
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _body_preview(body_text: str, max_length: int = 480) -> str:
    preview = " ".join((body_text or "").split())
    if len(preview) <= max_length:
        return preview
    return preview[: max_length - 1].rstrip() + "..."


def _serialize_vmail_message(message):
    received_at = getattr(message, "receivedAt", None) or getattr(message, "processedAt", None)
    return {
        "id": message.id,
        "mailbox": message.recipient_alias,
        "mailboxType": getattr(message, "mailbox_type", None) or "vlink",
        "reference": message.recipient_alias,
        "from": message.from_header,
        "replyTo": message.reply_to,
        "subject": message.subject,
        "receivedAt": _isoformat_utc(received_at),
        "receivedLabel": _received_label(received_at),
        "deliveryStatus": message.delivery_status,
        "isUnread": not message.is_read,
        "snippet": message.snippet,
        "bodyPreview": _body_preview(message.body_text),
        "senderTrust": message.sender_trust or vmailMessageRepository.DEFAULT_SENDER_TRUST,
        "notaryStatus": message.notary_status or vmailMessageRepository.DEFAULT_NOTARY_STATUS,
        "identityStatus": message.identity_status or vmailMessageRepository.DEFAULT_IDENTITY_STATUS,
        "governanceStatus": message.governance_status or vmailMessageRepository.DEFAULT_GOVERNANCE_STATUS,
    }


def _resolve_account_for_telegram_id(telegram_id: int):
    link = telegramLinkRepository.find_active_by_telegram_id(telegram_id)
    if link is None:
        return None, None
    return link, worldKycAccountRepository.find_by_user_id(link.userId)


async def _resolve_tma_user_from_json(request: web.Request):
    try:
        data = await request.json()
    except json.JSONDecodeError as exc:
        raise web.HTTPBadRequest(
            text=json.dumps({"error": "Bad Request", "message": str(exc)}),
            content_type="application/json",
        )

    init_data = data.get("initData")
    if not isinstance(init_data, str):
        raise web.HTTPBadRequest(
            text=json.dumps({"error": "initData is required", "expected": "string"}),
            content_type="application/json",
        )

    try:
        user = authenticate_mini_app_user(init_data)
    except TelegramMiniAppAuthError as exc:
        raise web.HTTPUnauthorized(
            text=web.json_response({"error": "Unauthorized", "details": str(exc)}).text,
            content_type="application/json",
        )

    return user, data


def _resolve_tma_user_from_header(request: web.Request):
    init_data = request.headers.get("X-Telegram-Init-Data")
    if not init_data:
        raise web.HTTPUnauthorized(
            text=web.json_response({"error": "Unauthorized", "details": "X-Telegram-Init-Data is required"}).text,
            content_type="application/json",
        )

    try:
        return authenticate_mini_app_user(init_data)
    except TelegramMiniAppAuthError as exc:
        raise web.HTTPUnauthorized(
            text=web.json_response({"error": "Unauthorized", "details": str(exc)}).text,
            content_type="application/json",
        )


def _serialize_stored_vlink(link):
    return {
        "id": link.reference,
        "reference": link.reference,
        "name": link.name or "Unnamed",
        "status": link.status or "Unknown",
        "mailboxAlias": getattr(link, "mailboxAlias", None),
        "url": f"{WKYC_VLINK_BASE_URL}{link.reference}",
    }


async def handle_bootstrap(request: web.Request):
    user, _data = await _resolve_tma_user_from_json(request)
    link, account = _resolve_account_for_telegram_id(user.telegram_id)
    linked = bool(link and account)
    return web.json_response(
        {
            "telegramUser": user.to_dict(),
            "linked": linked,
            "user": {
                "telegramId": user.telegram_id,
                "userId": account.userId if account else None,
                "emailAddress": account.emailAddress if account else None,
            },
        }
    )


async def handle_login(request: web.Request):
    user, data = await _resolve_tma_user_from_json(request)
    login_id = data.get("loginId")
    password = data.get("password")
    if not isinstance(login_id, str) or not login_id:
        logger.warning("TMA login rejected for telegramId=%s: missing loginId", user.telegram_id)
        return _json_error("loginId is required", 400)
    if not isinstance(password, str) or not password:
        logger.warning(
            "TMA login rejected for telegramId=%s loginId=%s: missing password",
            user.telegram_id,
            _mask_login_id(login_id),
        )
        return _json_error("password is required", 400)

    logger.info("TMA login attempt telegramId=%s loginId=%s", user.telegram_id, _mask_login_id(login_id))
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: authenticate(login_id, password),
        )
    except Exception:
        logger.exception(
            "TMA login crashed before upstream response telegramId=%s loginId=%s",
            user.telegram_id,
            _mask_login_id(login_id),
        )
        return _json_error("Login failed", 500, details="Internal server error")
    if not result.get("ok"):
        logger.warning(
            "TMA login upstream rejection telegramId=%s loginId=%s status=%s message=%s details=%s",
            user.telegram_id,
            _mask_login_id(login_id),
            result.get("status_code"),
            result.get("message"),
            result.get("details"),
        )
        return _build_upstream_error(result)

    payload = result.get("payload") or {}
    access_token, refresh_token = extract_tokens(payload)
    if not access_token or not refresh_token:
        logger.error(
            "TMA login succeeded without expected tokens telegramId=%s loginId=%s payload=%s",
            user.telegram_id,
            _mask_login_id(login_id),
            payload,
        )
        return _json_error(
            "WorldKyc Authenticate response did not include expected tokens",
            502,
            details=payload,
        )

    upstream_user_id = extract_user_id(payload, fallback=login_id)
    store_login_session(user.telegram_id, upstream_user_id, payload)
    user_settings = payload.get("userSettings") if isinstance(payload, dict) else {}
    worldKycAccountRepository.upsert(upstream_user_id, user_settings.get("emailAddress"))
    try:
        telegramLinkRepository.link(user.telegram_id, upstream_user_id)
    except ValueError as exc:
        return _json_error(str(exc), 409)
    logger.info(
        "TMA login linked telegramId=%s loginId=%s userId=%s",
        user.telegram_id,
        _mask_login_id(login_id),
        upstream_user_id,
    )
    try:
        await sync_user_vlinks(user.telegram_id)
    except (AuthSessionExpiredError, SessionNotLinkedError, RuntimeError) as exc:
        logger.warning("Initial verified link sync failed for telegramId=%s: %s", user.telegram_id, exc)
    return web.json_response(
        {
            "linked": True,
            "telegramUser": user.to_dict(),
            "user": {
                "telegramId": user.telegram_id,
                "userId": upstream_user_id,
                "userName": user_settings.get("userName"),
                "organizationName": user_settings.get("organizationName"),
                "emailAddress": user_settings.get("emailAddress"),
            },
        }
    )


async def handle_logout(request: web.Request):
    user, _data = await _resolve_tma_user_from_json(request)
    userRepository.clearUserTokens(user.telegram_id)
    telegramLinkRepository.revoke(user.telegram_id)
    return web.json_response(
        {
            "linked": False,
            "telegramUser": user.to_dict(),
        }
    )


async def handle_connection_code(request: web.Request):
    user, _data = await _resolve_tma_user_from_json(request)
    active_link = telegramLinkRepository.find_active_by_telegram_id(user.telegram_id)
    if active_link is not None:
        return _json_error("Telegram account is already linked", 409)
    code, record = telegramConnectionCodeRepository.create(user.telegram_id)
    separator = "&" if "?" in WKYC_TELEGRAM_CONNECT_URL else "?"
    return web.json_response(
        {
            "connectUrl": f"{WKYC_TELEGRAM_CONNECT_URL}{separator}code={code}",
            "expiresAt": _isoformat_utc(record.expiresAt),
        },
        status=201,
    )


async def handle_vlinks(request: web.Request):
    user = _resolve_tma_user_from_header(request)
    link, account = _resolve_account_for_telegram_id(user.telegram_id)
    if link is None or account is None:
        return _json_error("User is not linked", 404)
    links = verifiedLinkRepository.list_for_account(account.userId)
    return web.json_response({"items": [_serialize_stored_vlink(stored_link) for stored_link in links]})


async def handle_vmail_messages(request: web.Request):
    user = _resolve_tma_user_from_header(request)
    link, account = _resolve_account_for_telegram_id(user.telegram_id)
    if link is None or account is None:
        return _json_error("User is not linked", 404)

    requested_mailboxes = _split_references(request.query.get("mailboxes"))
    if not requested_mailboxes:
        requested_mailboxes = _split_references(request.query.get("references"))
    limit = _parse_int_query(request, "limit", 25, 1, 100)
    offset = _parse_int_query(request, "offset", 0, 0, 10000)
    unread_only = _parse_bool_query(request, "unreadOnly")

    messages = vmailMessageRepository.list_for_user(
        account.userId,
        mailboxes=requested_mailboxes,
        limit=limit,
        offset=offset,
        unread_only=unread_only,
    )
    return web.json_response(
        {
            "messages": [_serialize_vmail_message(message) for message in messages],
            "limit": limit,
            "offset": offset,
        }
    )


async def handle_vmail_message_read(request: web.Request):
    user = _resolve_tma_user_from_header(request)
    link, account = _resolve_account_for_telegram_id(user.telegram_id)
    if link is None or account is None:
        return _json_error("User is not linked", 404)

    try:
        message_id = int(request.match_info["id"])
    except (KeyError, ValueError):
        return _json_error("Message id must be an integer", 400)

    message = vmailMessageRepository.mark_read(
        message_id,
        user_id=account.userId,
    )
    if message is None:
        return _json_error("Message not found", 404)
    return web.json_response({"message": _serialize_vmail_message(message)})


async def handle_tma_index(_request: web.Request):
    index_file = FRONTEND_DIST_DIR / "index.html"
    if not index_file.exists():
        return _json_error(
            "TMA frontend is not built",
            503,
            details="Run `npm --prefix frontend install && npm --prefix frontend run build` first.",
        )
    return web.FileResponse(index_file)


async def handle_tma_asset(request: web.Request):
    asset_tail = request.match_info.get("tail", "")
    if not asset_tail:
        raise web.HTTPNotFound()

    asset_path = (FRONTEND_ASSETS_DIR / asset_tail).resolve()
    if FRONTEND_ASSETS_DIR.resolve() not in asset_path.parents or not asset_path.exists() or not asset_path.is_file():
        raise web.HTTPNotFound()

    return web.FileResponse(asset_path)
