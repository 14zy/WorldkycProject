from __future__ import annotations

from datetime import datetime, timezone

from config.dbConfig import SessionLocal
from data.model.worldKycAccount import WorldKycAccount


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def find_by_user_id(user_id: str):
    db = SessionLocal()
    try:
        return db.query(WorldKycAccount).filter(WorldKycAccount.userId == user_id).first()
    finally:
        db.close()


def upsert(user_id: str, email_address: str | None = None):
    normalized_user_id = (user_id or "").strip()
    if not normalized_user_id:
        raise ValueError("user_id is required")

    db = SessionLocal()
    try:
        account = db.query(WorldKycAccount).filter(WorldKycAccount.userId == normalized_user_id).first()
        now = _utcnow()
        if account is None:
            account = WorldKycAccount(
                userId=normalized_user_id,
                emailAddress=email_address,
                createdAt=now,
                updatedAt=now,
            )
            db.add(account)
        else:
            if email_address is not None:
                account.emailAddress = email_address
            account.updatedAt = now
        db.commit()
        db.refresh(account)
        return account
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
