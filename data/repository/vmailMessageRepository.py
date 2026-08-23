from __future__ import annotations

from datetime import datetime, timezone

from config.dbConfig import SessionLocal
from data.model.vmailMessage import VMailMessage


DEFAULT_SENDER_TRUST = "anonymous"
DEFAULT_NOTARY_STATUS = "N/A"
DEFAULT_IDENTITY_STATUS = "Not disclosed"
DEFAULT_GOVERNANCE_STATUS = "Review required"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_aliases(aliases: list[str]) -> list[str]:
    return sorted({(alias or "").strip().casefold() for alias in aliases if (alias or "").strip()})


def _build_snippet(body_text: str, max_length: int = 220) -> str:
    snippet = " ".join((body_text or "").split())
    if len(snippet) <= max_length:
        return snippet
    return snippet[: max_length - 1].rstrip() + "..."


def upsert_from_processed_message(
    *,
    mailbox: str,
    imap_uid: str,
    message_id: str | None,
    recipient_alias: str,
    telegram_id: int | None,
    user_id: str | None,
    from_header: str,
    reply_to: str | None,
    subject: str,
    body_text: str,
    delivery_status: str,
    error: str | None = None,
    received_at: datetime | None = None,
):
    normalized_alias = (recipient_alias or "").strip().casefold()
    if not normalized_alias:
        raise ValueError("recipient_alias is required")

    db = SessionLocal()
    try:
        message = (
            db.query(VMailMessage)
            .filter(
                VMailMessage.mailbox == mailbox,
                VMailMessage.imap_uid == imap_uid,
                VMailMessage.recipient_alias == normalized_alias,
            )
            .first()
        )
        if not message:
            message = VMailMessage(mailbox=mailbox, imap_uid=imap_uid, recipient_alias=normalized_alias)
            db.add(message)

        message.message_id = message_id
        message.telegramId = telegram_id
        message.userId = user_id
        message.from_header = from_header
        message.reply_to = reply_to
        message.subject = subject
        message.body_text = body_text
        message.snippet = _build_snippet(body_text)
        message.delivery_status = delivery_status
        message.receivedAt = received_at
        message.processedAt = _utcnow()
        message.error = error
        message.sender_trust = message.sender_trust or DEFAULT_SENDER_TRUST
        message.notary_status = message.notary_status or DEFAULT_NOTARY_STATUS
        message.identity_status = message.identity_status or DEFAULT_IDENTITY_STATUS
        message.governance_status = message.governance_status or DEFAULT_GOVERNANCE_STATUS

        db.commit()
        db.refresh(message)
        return message
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def list_for_aliases(
    aliases: list[str],
    *,
    limit: int = 25,
    offset: int = 0,
    unread_only: bool = False,
):
    normalized_aliases = _normalize_aliases(aliases)
    if not normalized_aliases:
        return []

    db = SessionLocal()
    try:
        query = db.query(VMailMessage).filter(VMailMessage.recipient_alias.in_(normalized_aliases))
        if unread_only:
            query = query.filter(VMailMessage.is_read.is_(False))
        return (
            query.order_by(VMailMessage.receivedAt.desc().nullslast(), VMailMessage.processedAt.desc())
            .offset(max(0, offset))
            .limit(max(1, limit))
            .all()
        )
    finally:
        db.close()


def mark_read(message_id: int, *, telegram_id: int | None = None, user_id: str | None = None):
    db = SessionLocal()
    try:
        query = db.query(VMailMessage).filter(VMailMessage.id == message_id)
        if telegram_id is not None:
            query = query.filter(VMailMessage.telegramId == telegram_id)
        if user_id is not None:
            query = query.filter(VMailMessage.userId == user_id)

        message = query.first()
        if not message:
            return None

        message.is_read = True
        db.commit()
        db.refresh(message)
        return message
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
