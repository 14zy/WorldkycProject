from datetime import datetime, timezone

from config.dbConfig import SessionLocal
from data.model.processedEmail import ProcessedEmail


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_by_mailbox_uid(mailbox: str, uid: str):
    db = SessionLocal()
    try:
        return (
            db.query(ProcessedEmail)
            .filter(ProcessedEmail.mailbox == mailbox, ProcessedEmail.imap_uid == uid)
            .first()
        )
    finally:
        db.close()


def mark_processed(
    mailbox: str,
    uid: str,
    *,
    message_id: str | None,
    recipient_alias: str | None,
    status: str,
    error: str | None = None,
):
    db = SessionLocal()
    try:
        entry = (
            db.query(ProcessedEmail)
            .filter(ProcessedEmail.mailbox == mailbox, ProcessedEmail.imap_uid == uid)
            .first()
        )
        if not entry:
            entry = ProcessedEmail(mailbox=mailbox, imap_uid=uid)
            db.add(entry)

        entry.message_id = message_id
        entry.recipient_alias = recipient_alias
        entry.status = status
        entry.error = error
        entry.processedAt = _utcnow()
        db.commit()
        db.refresh(entry)
        return entry
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
