from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from config.dbConfig import SessionLocal
from data.model.outboundVmailMessage import OutboundVmailMessage, ResendWebhookEvent
from data.model.vmailMessage import VMailMessage


COUNTED_SEND_STATUSES = (
    "submitting",
    "queued",
    "sent",
    "delivered",
    "bounced",
    "complained",
    "delayed",
    "failed",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def find_owned_inbound(message_id: int, user_id: str):
    db = SessionLocal()
    try:
        return (
            db.query(VMailMessage)
            .filter(VMailMessage.id == message_id, VMailMessage.userId == user_id)
            .first()
        )
    finally:
        db.close()


def find_by_request(user_id: str, client_request_id: str):
    db = SessionLocal()
    try:
        return (
            db.query(OutboundVmailMessage)
            .filter(
                OutboundVmailMessage.userId == user_id,
                OutboundVmailMessage.client_request_id == client_request_id,
            )
            .first()
        )
    finally:
        db.close()


def create_submission(**values):
    db = SessionLocal()
    try:
        now = _utcnow()
        message = OutboundVmailMessage(
            id=uuid4().hex,
            status="submitting",
            createdAt=now,
            updatedAt=now,
            **values,
        )
        db.add(message)
        db.commit()
        db.refresh(message)
        return message, True
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(OutboundVmailMessage)
            .filter(
                OutboundVmailMessage.userId == values["userId"],
                OutboundVmailMessage.client_request_id == values["client_request_id"],
            )
            .first()
        )
        if existing is None:
            raise
        return existing, False
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def retry_failed(message_id: str, correlation_id: str):
    db = SessionLocal()
    try:
        updated = (
            db.query(OutboundVmailMessage)
            .filter(
                OutboundVmailMessage.id == message_id,
                OutboundVmailMessage.status == "submission_failed",
            )
            .update(
                {
                    OutboundVmailMessage.status: "submitting",
                    OutboundVmailMessage.failure_category: None,
                    OutboundVmailMessage.correlation_id: correlation_id,
                    OutboundVmailMessage.updatedAt: _utcnow(),
                },
                synchronize_session=False,
            )
        )
        db.commit()
        message = db.query(OutboundVmailMessage).filter(OutboundVmailMessage.id == message_id).first()
        return message, updated == 1
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def mark_queued(message_id: str, resend_email_id: str):
    db = SessionLocal()
    try:
        message = db.query(OutboundVmailMessage).filter(OutboundVmailMessage.id == message_id).one()
        message.status = "queued"
        message.resend_email_id = resend_email_id
        message.failure_category = None
        message.updatedAt = _utcnow()
        db.commit()
        db.refresh(message)
        return message
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def mark_failed(message_id: str, failure_category: str):
    db = SessionLocal()
    try:
        message = db.query(OutboundVmailMessage).filter(OutboundVmailMessage.id == message_id).one()
        message.status = "submission_failed"
        message.failure_category = failure_category
        message.updatedAt = _utcnow()
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def count_recent(*, user_id: str, reference: str | None = None, since: datetime | None = None) -> int:
    since = since or (_utcnow() - timedelta(hours=1))
    db = SessionLocal()
    try:
        query = db.query(OutboundVmailMessage).filter(
            OutboundVmailMessage.userId == user_id,
            OutboundVmailMessage.createdAt >= since,
            OutboundVmailMessage.status.in_(COUNTED_SEND_STATUSES),
        )
        if reference is not None:
            query = query.filter(OutboundVmailMessage.reference == reference)
        return query.count()
    finally:
        db.close()


def apply_webhook_event(event_id: str, event_type: str, resend_email_id: str, rfc_message_id=None):
    db = SessionLocal()
    try:
        if db.query(ResendWebhookEvent).filter(ResendWebhookEvent.event_id == event_id).first():
            return False
        message = (
            db.query(OutboundVmailMessage)
            .filter(OutboundVmailMessage.resend_email_id == resend_email_id)
            .first()
        )
        db.add(ResendWebhookEvent(event_id=event_id, event_type=event_type, receivedAt=_utcnow()))
        if message is not None:
            status_by_event = {
                "email.sent": "sent",
                "email.delivered": "delivered",
                "email.bounced": "bounced",
                "email.complained": "complained",
                "email.delivery_delayed": "delayed",
                "email.failed": "failed",
            }
            next_status = status_by_event.get(event_type)
            if next_status in {"bounced", "complained", "failed", "delivered"}:
                message.status = next_status
            elif next_status == "delayed" and message.status in {"queued", "sent"}:
                message.status = next_status
            elif next_status == "sent" and message.status == "queued":
                message.status = next_status
            if rfc_message_id:
                message.rfc_message_id = rfc_message_id
            message.updatedAt = _utcnow()
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
