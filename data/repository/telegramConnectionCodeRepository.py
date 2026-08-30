from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from config.config import TELEGRAM_CONNECT_CODE_TTL_SECONDS
from config.dbConfig import SessionLocal
from data.model.telegramConnectionCode import TelegramConnectionCode
from data.model.telegramLink import TelegramLink
from data.model.worldKycAccount import WorldKycAccount


class ConnectionCodeError(ValueError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def create(telegram_id: int) -> tuple[str, TelegramConnectionCode]:
    raw_code = secrets.token_urlsafe(32)
    now = _utcnow()
    record = TelegramConnectionCode(
        codeHash=_hash_code(raw_code),
        telegramId=telegram_id,
        createdAt=now,
        expiresAt=now + timedelta(seconds=TELEGRAM_CONNECT_CODE_TTL_SECONDS),
        usedAt=None,
    )
    db = SessionLocal()
    try:
        db.add(record)
        db.commit()
        db.refresh(record)
        return raw_code, record
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def redeem_and_link(code: str, user_id: str, email_address: str | None = None) -> TelegramLink:
    normalized_code = (code or "").strip()
    normalized_user_id = (user_id or "").strip()
    if not normalized_code or not normalized_user_id:
        raise ConnectionCodeError("Connection code and user ID are required")

    db = SessionLocal()
    try:
        now = _utcnow()
        record = (
            db.query(TelegramConnectionCode)
            .filter(TelegramConnectionCode.codeHash == _hash_code(normalized_code))
            .with_for_update()
            .first()
        )
        if record is None or record.usedAt is not None:
            raise ConnectionCodeError("Connection code is invalid or already used")
        expires_at = record.expiresAt
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            raise ConnectionCodeError("Connection code has expired")

        account = db.query(WorldKycAccount).filter(WorldKycAccount.userId == normalized_user_id).first()
        if account is None:
            account = WorldKycAccount(
                userId=normalized_user_id,
                emailAddress=email_address,
                createdAt=now,
                updatedAt=now,
            )
            db.add(account)
        elif email_address is not None:
            account.emailAddress = email_address
            account.updatedAt = now

        link = db.query(TelegramLink).filter(TelegramLink.telegramId == record.telegramId).first()
        if link is not None and link.revokedAt is None and link.userId != normalized_user_id:
            raise ConnectionCodeError("Telegram account is already linked to another WorldKYC account")
        if link is None:
            link = TelegramLink(
                telegramId=record.telegramId,
                userId=normalized_user_id,
                linkedAt=now,
                revokedAt=None,
            )
            db.add(link)
        else:
            link.userId = normalized_user_id
            link.linkedAt = now
            link.revokedAt = None

        record.usedAt = now
        db.commit()
        db.refresh(link)
        return link
    except ConnectionCodeError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
