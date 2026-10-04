from __future__ import annotations

import asyncio
import email
import html
import imaplib
import logging
from email.header import decode_header
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime

import data.repository.processedEmailRepository as processedEmailRepository
import data.repository.userRepository as userRepository
import data.repository.verifiedLinkRepository as verifiedLinkRepository
import data.repository.vmailMessageRepository as vmailMessageRepository
import data.repository.telegramLinkRepository as telegramLinkRepository
import data.repository.worldKycAccountRepository as worldKycAccountRepository
from config.config import (
    IMAP_HOST,
    IMAP_MAILBOX,
    IMAP_PASSWORD,
    IMAP_POLL_INTERVAL_SECONDS,
    IMAP_PORT,
    IMAP_USE_SSL,
    IMAP_USERNAME,
    MAIL_INBOUND_DOMAINS,
    bot,
)
from services.outboundMailService import send_forward_email
from utils.mailSanitizer import chunk_telegram_text, html_to_text, sanitize_mail_text


logger = logging.getLogger(__name__)
RECIPIENT_HEADERS = ("To", "X-Original-To", "Envelope-To", "Delivered-To")
SYSTEM_MAILBOX_ALIAS = IMAP_USERNAME.partition("@")[0].strip().casefold() if IMAP_USERNAME else ""
STATUS_DELIVERED = "delivered"
STATUS_TELEGRAM_ONLY = "telegram_only"
STATUS_PARTIAL = "partial"
STATUS_PRIORITY = {
    STATUS_DELIVERED: 0,
    STATUS_TELEGRAM_ONLY: 1,
    STATUS_PARTIAL: 2,
}


def _imap_enabled() -> bool:
    return bool(IMAP_HOST and IMAP_USERNAME and IMAP_PASSWORD)


def _connect_imap():
    if IMAP_USE_SSL:
        client = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    else:
        client = imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
    client.login(IMAP_USERNAME, IMAP_PASSWORD)
    client.select(IMAP_MAILBOX)
    return client


def _fetch_unseen_messages():
    client = _connect_imap()
    try:
        status, data = client.uid("search", None, "UNSEEN")
        if status != "OK":
            raise RuntimeError("Failed to search IMAP mailbox")

        uids = [uid.decode("utf-8") for uid in (data[0] or b"").split() if uid]
        messages = []
        for uid in uids:
            status, payload = client.uid("fetch", uid.encode("utf-8"), "(RFC822)")
            if status != "OK" or not payload or not payload[0]:
                logger.warning("Failed to fetch IMAP message uid=%s", uid)
                continue
            raw_message = payload[0][1]
            messages.append((uid, email.message_from_bytes(raw_message)))
        return messages
    finally:
        try:
            client.close()
        except Exception:
            pass
        client.logout()


def _extract_aliases(message: Message) -> list[str]:
    aliases: list[str] = []
    for header_name in RECIPIENT_HEADERS:
        for header_value in message.get_all(header_name, []):
            for _display_name, address in getaddresses([header_value]):
                local_part, separator, domain = address.rpartition("@")
                if not separator or domain.strip().casefold() not in MAIL_INBOUND_DOMAINS:
                    continue
                normalized = local_part.strip().casefold()
                if normalized and normalized not in aliases:
                    aliases.append(normalized)
    return aliases


def _select_effective_aliases(aliases: list[str]) -> list[str]:
    target_aliases = [alias for alias in aliases if alias != SYSTEM_MAILBOX_ALIAS]
    if target_aliases:
        return target_aliases
    if SYSTEM_MAILBOX_ALIAS and SYSTEM_MAILBOX_ALIAS in aliases:
        return [SYSTEM_MAILBOX_ALIAS]
    return []


def _extract_body(message: Message) -> str:
    if message.is_multipart():
        plain_parts: list[str] = []
        html_parts: list[str] = []
        for part in message.walk():
            content_disposition = (part.get_content_disposition() or "").lower()
            if content_disposition == "attachment":
                continue
            content_type = (part.get_content_type() or "").lower()
            payload = part.get_payload(decode=True)
            charset = part.get_content_charset() or "utf-8"
            if payload is None:
                continue
            try:
                decoded = payload.decode(charset, errors="replace")
            except LookupError:
                decoded = payload.decode("utf-8", errors="replace")
            if content_type == "text/plain":
                plain_parts.append(decoded)
            elif content_type == "text/html":
                html_parts.append(decoded)
        if plain_parts:
            return "\n\n".join(plain_parts)
        if html_parts:
            return html_to_text("\n\n".join(html_parts))
        return ""

    payload = message.get_payload(decode=True)
    if payload is None:
        return ""
    charset = message.get_content_charset() or "utf-8"
    try:
        decoded = payload.decode(charset, errors="replace")
    except LookupError:
        decoded = payload.decode("utf-8", errors="replace")

    if (message.get_content_type() or "").lower() == "text/html":
        return html_to_text(decoded)
    return decoded


def _decode_header_value(value: str | None) -> str:
    if not value:
        return ""

    decoded_parts: list[str] = []
    for part, encoding in decode_header(value):
        if isinstance(part, bytes):
            charset = encoding or "utf-8"
            try:
                decoded_parts.append(part.decode(charset, errors="replace"))
            except LookupError:
                decoded_parts.append(part.decode("utf-8", errors="replace"))
        else:
            decoded_parts.append(part)
    return "".join(decoded_parts)


def _build_plain_forward_content(message: Message, recipient_alias: str) -> str:
    display_alias = recipient_alias.upper()
    subject = sanitize_mail_text(_decode_header_value(message.get("Subject"))) or "(no subject)"
    sender = sanitize_mail_text(_decode_header_value(message.get("From"))) or "(unknown sender)"
    body = sanitize_mail_text(_extract_body(message)) or "(empty message)"
    return f"To: {display_alias}\nFrom: {sender}\nSubject: {subject}\n\n{body}"


def _parse_received_at(message: Message):
    raw_date = message.get("Date")
    if not raw_date:
        return None
    try:
        return parsedate_to_datetime(raw_date)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def _extract_reply_to(message: Message, from_header: str) -> str | None:
    reply_to = sanitize_mail_text(_decode_header_value(message.get("Reply-To")))
    return reply_to or from_header or None


def _extract_inbox_content(message: Message):
    from_header = sanitize_mail_text(_decode_header_value(message.get("From"))) or "(unknown sender)"
    subject = sanitize_mail_text(_decode_header_value(message.get("Subject"))) or "(no subject)"
    body_text = sanitize_mail_text(_extract_body(message)) or "(empty message)"
    return {
        "from_header": from_header,
        "reply_to": _extract_reply_to(message, from_header),
        "references": sanitize_mail_text(_decode_header_value(message.get("References"))) or None,
        "subject": subject,
        "body_text": body_text,
        "received_at": _parse_received_at(message),
    }


def _build_telegram_message(message: Message, recipient_alias: str) -> str:
    plain_text = _build_plain_forward_content(message, recipient_alias)
    escaped = html.escape(plain_text)
    escaped = escaped.replace("To: ", "<b>To:</b> ", 1)
    escaped = escaped.replace("\nFrom: ", "\n<b>From:</b> ", 1)
    escaped = escaped.replace("\nSubject: ", "\n<b>Subject:</b> ", 1)
    return escaped


async def _deliver_to_telegram(telegram_id: int, text: str):
    for chunk in chunk_telegram_text(text):
        await bot.send_message(chat_id=telegram_id, text=chunk, parse_mode="HTML")


def _deliver_to_user_email(message: Message, recipient_alias: str, recipient_email: str):
    subject = sanitize_mail_text(_decode_header_value(message.get("Subject"))) or "(no subject)"
    sender_header = sanitize_mail_text(_decode_header_value(message.get("From"))) or ""
    body = _build_plain_forward_content(message, recipient_alias)
    send_forward_email(
        recipient_alias=recipient_alias,
        recipient_email=recipient_email,
        sender_header=sender_header,
        subject=subject,
        body=body,
    )


def _merge_status(current_status: str | None, next_status: str) -> str:
    if current_status is None:
        return next_status
    if STATUS_PRIORITY[next_status] > STATUS_PRIORITY[current_status]:
        return next_status
    if current_status == STATUS_TELEGRAM_ONLY and next_status == STATUS_DELIVERED:
        return STATUS_PARTIAL
    if current_status == STATUS_DELIVERED and next_status == STATUS_TELEGRAM_ONLY:
        return STATUS_PARTIAL
    return current_status


def _is_direct_link_routable(link) -> bool:
    status = (getattr(link, "status", None) or "").strip().casefold()
    return not status or status == "active"


def _is_managed_forwarding_address(address: str | None) -> bool:
    if not address:
        return False
    parsed = getaddresses([address])
    if len(parsed) != 1:
        return False
    _name, addr_spec = parsed[0]
    _local, separator, domain = addr_spec.rpartition("@")
    return bool(separator and domain.strip().casefold() in MAIL_INBOUND_DOMAINS)


async def _process_message(uid: str, message: Message):
    if processedEmailRepository.get_by_mailbox_uid(IMAP_MAILBOX, uid):
        return

    message_id = message.get("Message-ID")
    aliases = _extract_aliases(message)
    effective_aliases = _select_effective_aliases(aliases)
    if not effective_aliases:
        logger.warning("Skipping IMAP message uid=%s message_id=%s without recipient alias", uid, message_id)
        return

    resolved_any = False
    resolved_deliveries: list[tuple[str, str, object]] = []
    target_deliveries: dict[str, tuple[str, str, object]] = {}
    unmatched_aliases: list[str] = []
    aggregate_status: str | None = None
    aggregate_alias: str | None = None
    aggregate_errors: list[str] = []
    for alias in effective_aliases:
        verified_link = verifiedLinkRepository.find_by_reference(alias)
        mailbox_type = "vlink"
        if not verified_link or not _is_direct_link_routable(verified_link):
            alias_links = verifiedLinkRepository.list_active_by_mailbox_alias(alias)
            if alias_links:
                verified_link = alias_links[0]
                mailbox_type = "alias"
            else:
                verified_link = None
        if verified_link is None:
            unmatched_aliases.append(alias)
            continue
        resolved_deliveries.append((alias, mailbox_type, verified_link))
        owner_user_id = getattr(verified_link, "userId", None)
        owner_key = f"user:{owner_user_id}" if owner_user_id else f"telegram:{verified_link.telegramId}"
        target_deliveries.setdefault(owner_key, (alias, mailbox_type, verified_link))

    delivery_results: dict[str, tuple[str, str | None, int | None]] = {}
    for owner_key, (alias, _mailbox_type, verified_link) in target_deliveries.items():
        owner_user_id = getattr(verified_link, "userId", None)
        account = worldKycAccountRepository.find_by_user_id(owner_user_id) if owner_user_id else None
        active_telegram_links = (
            telegramLinkRepository.list_active_for_user(owner_user_id) if owner_user_id else []
        )
        telegram_ids = list(dict.fromkeys(link.telegramId for link in active_telegram_links))
        legacy_telegram_id = getattr(verified_link, "telegramId", None)
        if not telegram_ids and legacy_telegram_id is not None:
            telegram_ids = [legacy_telegram_id]

        telegram_delivered = False
        for telegram_id in telegram_ids:
            text = _build_telegram_message(message, alias)
            await _deliver_to_telegram(telegram_id, text)
            telegram_delivered = True

        resolved_any = True
        if aggregate_alias is None:
            aggregate_alias = alias

        status = STATUS_TELEGRAM_ONLY if telegram_delivered else STATUS_PARTIAL
        error = None
        legacy_user = (
            userRepository.findUserByTelegramId(legacy_telegram_id)
            if account is None and legacy_telegram_id is not None
            else None
        )
        email_address = (
            getattr(account, "emailAddress", None)
            or getattr(legacy_user, "emailAddress", None)
        )
        if email_address and not _is_managed_forwarding_address(email_address):
            try:
                _deliver_to_user_email(message, alias, email_address)
                status = STATUS_DELIVERED
            except Exception as exc:
                status = STATUS_PARTIAL
                error = str(exc)
                logger.warning(
                    "Outbound alias forwarding failed uid=%s message_id=%s alias=%s userId=%s email=%s: %s",
                    uid,
                    message_id,
                    alias,
                    owner_user_id,
                    email_address,
                    exc,
                )
        elif email_address:
            error = "Forwarding to the managed inbound domain is disabled"
            logger.warning(
                "Skipping forwarding loop uid=%s message_id=%s alias=%s userId=%s email=%s",
                uid,
                message_id,
                alias,
                owner_user_id,
                email_address,
            )
        else:
            error = "User email address not available" if telegram_delivered else "No delivery channel available"

        delivery_results[owner_key] = (status, error, telegram_ids[0] if telegram_ids else None)
        aggregate_status = _merge_status(aggregate_status, status)
        if error and error not in aggregate_errors:
            aggregate_errors.append(error)

    if resolved_any:
        inbox_content = _extract_inbox_content(message)
        for alias, mailbox_type, verified_link in resolved_deliveries:
            owner_user_id = getattr(verified_link, "userId", None)
            owner_key = f"user:{owner_user_id}" if owner_user_id else f"telegram:{verified_link.telegramId}"
            status, error, delivery_telegram_id = delivery_results.get(
                owner_key,
                (STATUS_PARTIAL, "No delivery channel available", None),
            )
            vmailMessageRepository.upsert_from_processed_message(
                mailbox=IMAP_MAILBOX,
                imap_uid=uid,
                message_id=message_id,
                references=inbox_content["references"],
                recipient_alias=alias,
                mailbox_type=mailbox_type,
                telegram_id=delivery_telegram_id,
                user_id=owner_user_id,
                from_header=inbox_content["from_header"],
                reply_to=inbox_content["reply_to"],
                subject=inbox_content["subject"],
                body_text=inbox_content["body_text"],
                delivery_status=status,
                error=error,
                received_at=inbox_content["received_at"],
            )

    if resolved_any:
        processedEmailRepository.mark_processed(
            IMAP_MAILBOX,
            uid,
            message_id=message_id,
            recipient_alias=aggregate_alias,
            status=aggregate_status or STATUS_TELEGRAM_ONLY,
            error="; ".join(aggregate_errors) if aggregate_errors else None,
        )

    if unmatched_aliases and resolved_any:
        logger.info(
            "IMAP message uid=%s message_id=%s delivered with unmatched aliases=%s",
            uid,
            message_id,
            ",".join(unmatched_aliases),
        )

    if not resolved_any:
        for alias in unmatched_aliases:
            logger.warning("No local verified link match for uid=%s message_id=%s alias=%s", uid, message_id, alias)
        logger.warning("IMAP message uid=%s message_id=%s had no deliverable recipients", uid, message_id)


async def poll_loop():
    if not _imap_enabled():
        logger.info("IMAP mail ingress disabled: missing IMAP_HOST or credentials")
        return

    while True:
        try:
            loop = asyncio.get_running_loop()
            messages = await loop.run_in_executor(None, _fetch_unseen_messages)
            for uid, message in messages:
                try:
                    await _process_message(uid, message)
                except Exception:
                    logger.exception("IMAP message processing failed uid=%s", uid)
        except Exception:
            logger.exception("IMAP poll loop failed")

        await asyncio.sleep(IMAP_POLL_INTERVAL_SECONDS)
