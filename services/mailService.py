import asyncio
import email
import html
import imaplib
import logging
from email.header import decode_header
from email.message import Message
from email.utils import getaddresses

import data.repository.processedEmailRepository as processedEmailRepository
import data.repository.verifiedLinkRepository as verifiedLinkRepository
from config.config import (
    IMAP_HOST,
    IMAP_MAILBOX,
    IMAP_PASSWORD,
    IMAP_POLL_INTERVAL_SECONDS,
    IMAP_PORT,
    IMAP_USE_SSL,
    IMAP_USERNAME,
    bot,
)
from utils.mailSanitizer import chunk_telegram_text, html_to_text, sanitize_mail_text


logger = logging.getLogger(__name__)
RECIPIENT_HEADERS = ("To", "X-Original-To", "Envelope-To", "Delivered-To")
SYSTEM_MAILBOX_ALIAS = IMAP_USERNAME.partition("@")[0].strip().casefold() if IMAP_USERNAME else ""


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
        header_value = message.get(header_name)
        if not header_value:
            continue
        for _display_name, address in getaddresses([header_value]):
            local_part = address.partition("@")[0].strip()
            if local_part:
                normalized = local_part.casefold()
                if normalized not in aliases:
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


def _build_telegram_message(message: Message, recipient_alias: str) -> str:
    display_alias = html.escape(recipient_alias.upper())
    subject = html.escape(sanitize_mail_text(_decode_header_value(message.get("Subject"))) or "(no subject)")
    sender = html.escape(sanitize_mail_text(_decode_header_value(message.get("From"))) or "(unknown sender)")
    body = html.escape(sanitize_mail_text(_extract_body(message)) or "(empty message)")
    return f"<b>To:</b> {display_alias}\n<b>From:</b> {sender}\n<b>Subject:</b> {subject}\n\n{body}"


async def _deliver_to_telegram(telegram_id: int, text: str):
    for chunk in chunk_telegram_text(text):
        await bot.send_message(chat_id=telegram_id, text=chunk, parse_mode="HTML")


async def _process_message(uid: str, message: Message):
    if processedEmailRepository.get_by_mailbox_uid(IMAP_MAILBOX, uid):
        return

    message_id = message.get("Message-ID")
    aliases = _extract_aliases(message)
    effective_aliases = _select_effective_aliases(aliases)
    if not effective_aliases:
        logger.warning("Skipping IMAP message uid=%s message_id=%s without recipient alias", uid, message_id)
        return

    delivered_any = False
    delivered_to: set[int] = set()
    unmatched_aliases: list[str] = []
    for alias in effective_aliases:
        verified_link = verifiedLinkRepository.find_by_reference(alias)
        if not verified_link:
            unmatched_aliases.append(alias)
            continue
        if verified_link.telegramId in delivered_to:
            continue

        text = _build_telegram_message(message, alias)
        await _deliver_to_telegram(verified_link.telegramId, text)
        delivered_to.add(verified_link.telegramId)
        delivered_any = True
        processedEmailRepository.mark_processed(
            IMAP_MAILBOX,
            uid,
            message_id=message_id,
            recipient_alias=alias,
            status="delivered",
        )

    if unmatched_aliases and delivered_any:
        logger.info(
            "IMAP message uid=%s message_id=%s delivered with unmatched aliases=%s",
            uid,
            message_id,
            ",".join(unmatched_aliases),
        )

    if not delivered_any:
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
                except Exception as exc:
                    logger.exception("IMAP message processing failed uid=%s", uid)
                    processedEmailRepository.mark_processed(
                        IMAP_MAILBOX,
                        uid,
                        message_id=message.get("Message-ID"),
                        recipient_alias=None,
                        status="error",
                        error=str(exc),
                    )
        except Exception:
            logger.exception("IMAP poll loop failed")

        await asyncio.sleep(IMAP_POLL_INTERVAL_SECONDS)
