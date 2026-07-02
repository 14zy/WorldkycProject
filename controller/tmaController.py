import asyncio
import json
import logging
from pathlib import Path

from aiohttp import web

import data.repository.userRepository as userRepository
from api.worldKycApi import (
    authenticate,
    extract_tokens,
    extract_user_id,
    extract_verified_links,
    get_verified_links,
)
from config.config import WKYC_VLINK_BASE_URL
from services.sessionService import (
    AUTH_SESSION_EXPIRED_CODE,
    AuthSessionExpiredError,
    SessionNotLinkedError,
    call_with_valid_session,
    resolve_link_state,
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
    app.router.add_get("/api/tma/vlinks", handle_vlinks)
    app.router.add_get("/tma/assets/{tail:.*}", handle_tma_asset)
    app.router.add_get("/tma", handle_tma_index)
    app.router.add_get("/tma/{tail:.*}", handle_tma_index)


def _json_error(message: str, status: int, *, details=None):
    payload = {"error": message}
    if details is not None:
        payload["details"] = details
    return web.json_response(payload, status=status)


def _session_expired_response():
    return web.json_response(
        {"error": "Session expired", "code": AUTH_SESSION_EXPIRED_CODE},
        status=401,
    )


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


def _normalize_vlinks(payload):
    items = []
    for link in extract_verified_links(payload):
        reference = link.get("verifiedLinkReference") or link.get("reference")
        name = link.get("verifiedLinkName") or link.get("name") or "Unnamed"
        status = link.get("verifiedLinkStatusTypeName") or link.get("statusTypeName") or "Unknown"
        if not reference:
            continue
        link_id = str(link.get("verifiedLinkId") or link.get("id") or reference)
        items.append(
            {
                "id": link_id,
                "reference": reference,
                "name": name,
                "status": status,
                "url": f"{WKYC_VLINK_BASE_URL}{reference}",
            }
        )
    return items


async def handle_bootstrap(request: web.Request):
    user, _data = await _resolve_tma_user_from_json(request)
    linked_user, linked = await resolve_link_state(user.telegram_id)
    return web.json_response(
        {
            "telegramUser": user.to_dict(),
            "linked": linked,
            "user": {
                "telegramId": user.telegram_id,
                "userId": linked_user.userId if linked_user else None,
                "emailAddress": linked_user.emailAddress if linked_user else None,
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
    user_settings = payload.get("userSettings") if isinstance(payload, dict) else {}
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
    return web.json_response(
        {
            "linked": False,
            "telegramUser": user.to_dict(),
        }
    )


async def handle_vlinks(request: web.Request):
    user = _resolve_tma_user_from_header(request)
    linked_user = userRepository.findUserByTelegramId(user.telegram_id)
    if linked_user is None or not linked_user.accessToken or not linked_user.refreshToken:
        return _json_error("User is not linked", 404)

    try:
        result = await call_with_valid_session(
            user.telegram_id,
            lambda token: get_verified_links(token),
        )
    except AuthSessionExpiredError:
        return _session_expired_response()
    except SessionNotLinkedError:
        return _json_error("User is not linked", 404)
    if not result.get("ok"):
        logger.error(
            "Verified links upstream failure for telegramId=%s: status=%s details=%s",
            user.telegram_id,
            result.get("status_code"),
            result.get("details"),
        )
        return _build_upstream_error(result)

    try:
        await sync_user_vlinks(user.telegram_id, payload=result.get("payload"))
    except (AuthSessionExpiredError, SessionNotLinkedError, RuntimeError) as exc:
        logger.warning("Verified link cache sync failed for telegramId=%s: %s", user.telegram_id, exc)

    return web.json_response({"items": _normalize_vlinks(result.get("payload"))})


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
