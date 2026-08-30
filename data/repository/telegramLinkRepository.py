from __future__ import annotations

from datetime import datetime, timezone

from config.dbConfig import SessionLocal
from data.model.telegramLink import TelegramLink


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def find_active_by_telegram_id(telegram_id: int):
    db = SessionLocal()
    try:
        return (
            db.query(TelegramLink)
            .filter(
                TelegramLink.telegramId == telegram_id,
                TelegramLink.revokedAt.is_(None),
            )
            .first()
        )
    finally:
        db.close()


def list_active_for_user(user_id: str):
    db = SessionLocal()
    try:
        return (
            db.query(TelegramLink)
            .filter(TelegramLink.userId == user_id, TelegramLink.revokedAt.is_(None))
            .order_by(TelegramLink.telegramId.asc())
            .all()
        )
    finally:
        db.close()


def link(telegram_id: int, user_id: str):
    db = SessionLocal()
    try:
        existing = db.query(TelegramLink).filter(TelegramLink.telegramId == telegram_id).first()
        if existing is not None and existing.revokedAt is None and existing.userId != user_id:
            raise ValueError("Telegram account is already linked to another WorldKYC account")

        now = _utcnow()
        if existing is None:
            existing = TelegramLink(
                telegramId=telegram_id,
                userId=user_id,
                linkedAt=now,
                revokedAt=None,
            )
            db.add(existing)
        else:
            existing.userId = user_id
            existing.linkedAt = now
            existing.revokedAt = None
        db.commit()
        db.refresh(existing)
        return existing
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def revoke(telegram_id: int) -> bool:
    db = SessionLocal()
    try:
        existing = (
            db.query(TelegramLink)
            .filter(TelegramLink.telegramId == telegram_id, TelegramLink.revokedAt.is_(None))
            .first()
        )
        if existing is None:
            return False
        existing.revokedAt = _utcnow()
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
