from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import logging
import time
from datetime import timezone
from uuid import uuid4

from aiohttp import web

import data.repository.verifiedLinkRepository as verifiedLinkRepository
import data.repository.vmailMessageRepository as vmailMessageRepository
import data.repository.outboundVmailMessageRepository as outboundVmailMessageRepository
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
from config.config import RESEND_WEBHOOK_SECRET
from services.outboundMailService import ResendProviderError
from services.vmailSendService import (
    VmailSendError,
    derive_compose,
    derive_reply,
    submit as submit_vmail,
    validate_client_request_id,
)


logger = logging.getLogger(__name__)


def register_wkyc_delegated_routes(app: web.Application):
    app.router.add_get("/api/internal/v1/vlinks", handle_vlinks)
    app.router.add_put("/api/internal/v1/vlinks", handle_vlink_sync)
    app.router.add_get("/api/internal/v1/vmail/messages", handle_vmail_messages)
    app.router.add_post("/api/internal/v1/vmail/messages", handle_vmail_compose)
    app.router.add_post("/api/internal/v1/vmail/messages/{id}/reply", handle_vmail_reply)
    app.router.add_post("/api/internal/v1/vmail/messages/{id}/read", handle_vmail_message_read)
    app.router.add_post("/api/webhooks/resend", handle_resend_webhook)
    app.router.add_post("/api/internal/v1/telegram-links/redeem", handle_telegram_link_redeem)


def _json_error(message: str, status: int):
    return web.json_response({"error": message}, status=status)


def _assertion_from_request(request: web.Request, required_scope: str, *, exact_scope: bool = False):
    authorization = request.headers.get("Authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.casefold() != "bearer" or not token.strip():
        raise web.HTTPUnauthorized(
            text=json.dumps({"error": "Bearer assertion is required"}),
            content_type="application/json",
        )
    try:
        assertion = validate_wkyc_assertion(
            token.strip(),
            None if exact_scope else required_scope,
        )
    except WkycAssertionError as exc:
        raise web.HTTPUnauthorized(
            text=json.dumps({"error": "Invalid WKYC assertion", "details": str(exc)}),
            content_type="application/json",
        ) from exc
    if exact_scope and assertion.scopes != {required_scope}:
        raise web.HTTPForbidden(
            text=json.dumps({"error": f"Assertion does not grant exactly {required_scope}"}),
            content_type="application/json",
        )
    return assertion


def _correlation_id() -> str:
    return uuid4().hex


def _serialize_outbound(message):
    created_at = message.createdAt
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return {
        "message": {
            "id": message.id,
            "status": "queued",
            "createdAt": created_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
    }


async def _outbound_payload(request: web.Request):
    try:
        payload = await request.json()
    except (json.JSONDecodeError, ValueError):
        raise VmailSendError("Request body must be valid JSON") from None
    if not isinstance(payload, dict):
        raise VmailSendError("Request body must be a JSON object")
    return payload


async def _handle_outbound(request: web.Request, *, reply: bool):
    correlation_id = _correlation_id()
    try:
        assertion = _assertion_from_request(request, "vmail.write", exact_scope=True)
        _require_account(assertion.user_id)
        payload = await _outbound_payload(request)
        client_request_id = validate_client_request_id(payload)
        if reply:
            try:
                message_id = int(request.match_info["id"])
            except (KeyError, ValueError):
                raise VmailSendError("Message id must be an integer") from None
            derived = derive_reply(assertion.user_id, message_id, payload)
            kind = "reply"
        else:
            derived = derive_compose(assertion.user_id, payload)
            kind = "compose"
        record = await asyncio.to_thread(
            submit_vmail,
            user_id=assertion.user_id,
            client_request_id=client_request_id,
            kind=kind,
            derived=derived,
            correlation_id=correlation_id,
        )
        response = web.json_response(_serialize_outbound(record))
    except VmailSendError as exc:
        response = _json_error(str(exc), exc.status)
    except ResendProviderError as exc:
        logger.warning("VMail provider submission failed correlation_id=%s category=%s", correlation_id, exc.category)
        response = _json_error(
            "Email provider is temporarily unavailable" if exc.temporary else "Email provider rejected the message",
            503 if exc.temporary else 502,
        )
    except web.HTTPException as exc:
        exc.headers["X-Correlation-ID"] = correlation_id
        raise
    response.headers["X-Correlation-ID"] = correlation_id
    return response


async def handle_vmail_compose(request: web.Request):
    return await _handle_outbound(request, reply=False)


async def handle_vmail_reply(request: web.Request):
    return await _handle_outbound(request, reply=True)


def _verify_resend_webhook(raw_body: bytes, headers) -> str:
    if not RESEND_WEBHOOK_SECRET:
        raise ValueError("Webhook verification is not configured")
    event_id = headers.get("svix-id", "")
    timestamp = headers.get("svix-timestamp", "")
    signature_header = headers.get("svix-signature", "")
    try:
        timestamp_number = int(timestamp)
    except ValueError:
        raise ValueError("Invalid webhook timestamp") from None
    if not event_id or abs(int(time.time()) - timestamp_number) > 300:
        raise ValueError("Invalid webhook timestamp")
    secret_value = RESEND_WEBHOOK_SECRET.removeprefix("whsec_")
    try:
        secret = base64.b64decode(secret_value, validate=True)
    except (ValueError, binascii.Error):
        secret = secret_value.encode("utf-8")
    signed = f"{event_id}.{timestamp}.".encode("utf-8") + raw_body
    expected = base64.b64encode(hmac.new(secret, signed, hashlib.sha256).digest()).decode("ascii")
    candidates = [part.removeprefix("v1,") for part in signature_header.split()]
    if not any(hmac.compare_digest(expected, candidate) for candidate in candidates):
        raise ValueError("Invalid webhook signature")
    return event_id


async def handle_resend_webhook(request: web.Request):
    raw_body = await request.read()
    try:
        event_id = _verify_resend_webhook(raw_body, request.headers)
        event = json.loads(raw_body)
        event_type = event.get("type")
        data = event.get("data")
        resend_email_id = data.get("email_id") if isinstance(data, dict) else None
        if not isinstance(event_type, str) or not isinstance(resend_email_id, str):
            raise ValueError("Invalid webhook payload")
        rfc_message_id = data.get("message_id")
        await asyncio.to_thread(
            outboundVmailMessageRepository.apply_webhook_event,
            event_id,
            event_type,
            resend_email_id,
            rfc_message_id if isinstance(rfc_message_id, str) else None,
        )
    except (ValueError, json.JSONDecodeError):
        return _json_error("Invalid webhook", 400)
    return web.json_response({"received": True})


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
