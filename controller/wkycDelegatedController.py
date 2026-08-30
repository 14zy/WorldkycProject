from __future__ import annotations

import json

from aiohttp import web

import data.repository.verifiedLinkRepository as verifiedLinkRepository
import data.repository.vmailMessageRepository as vmailMessageRepository
import data.repository.worldKycAccountRepository as worldKycAccountRepository
import data.repository.telegramConnectionCodeRepository as telegramConnectionCodeRepository
from controller.tmaController import (
    _parse_bool_query,
    _parse_int_query,
    _serialize_stored_vlink,
    _serialize_vmail_message,
    _split_references,
)
from utils.wkyc_assertion import WkycAssertionError, validate_wkyc_assertion


def register_wkyc_delegated_routes(app: web.Application):
    app.router.add_get("/api/internal/v1/vlinks", handle_vlinks)
    app.router.add_put("/api/internal/v1/vlinks", handle_vlink_sync)
    app.router.add_get("/api/internal/v1/vmail/messages", handle_vmail_messages)
    app.router.add_post("/api/internal/v1/vmail/messages/{id}/read", handle_vmail_message_read)
    app.router.add_post("/api/internal/v1/telegram-links/redeem", handle_telegram_link_redeem)


def _json_error(message: str, status: int):
    return web.json_response({"error": message}, status=status)


def _assertion_from_request(request: web.Request, required_scope: str):
    authorization = request.headers.get("Authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.casefold() != "bearer" or not token.strip():
        raise web.HTTPUnauthorized(
            text=json.dumps({"error": "Bearer assertion is required"}),
            content_type="application/json",
        )
    try:
        return validate_wkyc_assertion(token.strip(), required_scope)
    except WkycAssertionError as exc:
        raise web.HTTPUnauthorized(
            text=json.dumps({"error": "Invalid WKYC assertion", "details": str(exc)}),
            content_type="application/json",
        ) from exc


def _require_account(user_id: str):
    account = worldKycAccountRepository.find_by_user_id(user_id)
    if account is None:
        raise web.HTTPNotFound(
            text=json.dumps({"error": "WorldKYC account is not synchronized"}),
            content_type="application/json",
        )
    return account


async def handle_vlinks(request: web.Request):
    assertion = _assertion_from_request(request, "vlinks.read")
    _require_account(assertion.user_id)
    links = verifiedLinkRepository.list_for_account(assertion.user_id)
    return web.json_response({"items": [_serialize_stored_vlink(link) for link in links]})


async def handle_vlink_sync(request: web.Request):
    assertion = _assertion_from_request(request, "vlinks.sync")
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return _json_error("Request body must be valid JSON", 400)
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        return _json_error("items must be an array of VLink objects", 400)

    email_address = assertion.claims.get("email")
    if email_address is not None and not isinstance(email_address, str):
        return _json_error("Assertion email claim must be a string", 400)
    worldKycAccountRepository.upsert(assertion.user_id, email_address)
    references = verifiedLinkRepository.upsert_links_for_user(assertion.user_id, items)
    verifiedLinkRepository.delete_missing_links_for_account(assertion.user_id, references)
    links = verifiedLinkRepository.list_for_account(assertion.user_id)
    return web.json_response({"items": [_serialize_stored_vlink(link) for link in links]})


async def handle_vmail_messages(request: web.Request):
    assertion = _assertion_from_request(request, "vmail.read")
    _require_account(assertion.user_id)
    requested_references = _split_references(request.query.get("references"))
    if requested_references:
        links = verifiedLinkRepository.list_for_account_references(
            assertion.user_id,
            requested_references,
        )
    else:
        links = verifiedLinkRepository.list_for_account(assertion.user_id)

    messages = vmailMessageRepository.list_for_aliases(
        [link.reference for link in links],
        limit=_parse_int_query(request, "limit", 25, 1, 100),
        offset=_parse_int_query(request, "offset", 0, 0, 10000),
        unread_only=_parse_bool_query(request, "unreadOnly"),
    )
    return web.json_response({"messages": [_serialize_vmail_message(message) for message in messages]})


async def handle_vmail_message_read(request: web.Request):
    assertion = _assertion_from_request(request, "vmail.write")
    _require_account(assertion.user_id)
    try:
        message_id = int(request.match_info["id"])
    except (KeyError, ValueError):
        return _json_error("Message id must be an integer", 400)
    message = vmailMessageRepository.mark_read(message_id, user_id=assertion.user_id)
    if message is None:
        return _json_error("Message not found", 404)
    return web.json_response({"message": _serialize_vmail_message(message)})


async def handle_telegram_link_redeem(request: web.Request):
    assertion = _assertion_from_request(request, "telegram.link")
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return _json_error("Request body must be valid JSON", 400)
    code = payload.get("code") if isinstance(payload, dict) else None
    if not isinstance(code, str) or not code.strip():
        return _json_error("code is required", 400)
    email_address = assertion.claims.get("email")
    if email_address is not None and not isinstance(email_address, str):
        return _json_error("Assertion email claim must be a string", 400)
    try:
        link = telegramConnectionCodeRepository.redeem_and_link(
            code,
            assertion.user_id,
            email_address,
        )
    except telegramConnectionCodeRepository.ConnectionCodeError as exc:
        return _json_error(str(exc), 409)
    return web.json_response(
        {"linked": True, "telegramId": link.telegramId, "userId": link.userId}
    )
