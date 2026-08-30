from __future__ import annotations

from datetime import datetime, timezone

from config.dbConfig import SessionLocal
from data.model.verifiedLink import VerifiedLink


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def upsert_links_for_user(user_id: str, links: list[dict], telegram_id: int | None = None):
    db = SessionLocal()
    try:
        now = _utcnow()
        normalized_references: set[str] = set()
        for link in links:
            reference = (
                link.get("verifiedLinkReference")
                or link.get("reference")
                or ""
            ).strip()
            if not reference:
                continue

            normalized_reference = reference.casefold()
            normalized_references.add(normalized_reference)
            existing = db.query(VerifiedLink).filter(VerifiedLink.reference == normalized_reference).first()
            if not existing:
                existing = VerifiedLink(reference=normalized_reference)
                db.add(existing)

            existing.telegramId = telegram_id
            existing.userId = user_id
            existing.name = link.get("verifiedLinkName") or link.get("name")
            existing.status = link.get("verifiedLinkStatusTypeName") or link.get("statusTypeName")
            existing.updatedAt = now

        db.commit()
        return normalized_references
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def delete_missing_links_for_account(user_id: str, references: set[str]):
    db = SessionLocal()
    try:
        query = db.query(VerifiedLink).filter(VerifiedLink.userId == user_id)
        if references:
            query = query.filter(VerifiedLink.reference.notin_(references))
        query.delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def find_by_reference(reference: str):
    normalized_reference = (reference or "").strip().casefold()
    if not normalized_reference:
        return None

    db = SessionLocal()
    try:
        return db.query(VerifiedLink).filter(VerifiedLink.reference == normalized_reference).first()
    finally:
        db.close()


def list_for_account(user_id: str):
    db = SessionLocal()
    try:
        return (
            db.query(VerifiedLink)
            .filter(VerifiedLink.userId == user_id)
            .order_by(VerifiedLink.reference.asc())
            .all()
        )
    finally:
        db.close()


def list_for_account_references(user_id: str, references: list[str]):
    normalized_references = sorted(
        {
            (reference or "").strip().casefold()
            for reference in references
            if (reference or "").strip()
        }
    )
    if not normalized_references:
        return []

    db = SessionLocal()
    try:
        return (
            db.query(VerifiedLink)
            .filter(
                VerifiedLink.userId == user_id,
                VerifiedLink.reference.in_(normalized_references),
            )
            .order_by(VerifiedLink.reference.asc())
            .all()
        )
    finally:
        db.close()


# Transitional wrappers retained for callers deployed before the account cutover.
def upsert_links(telegram_id: int, user_id: str, links: list[dict]):
    return upsert_links_for_user(user_id, links, telegram_id=telegram_id)


def delete_missing_links_for_user(telegram_id: int, references: set[str]):
    db = SessionLocal()
    try:
        user_id = (
            db.query(VerifiedLink.userId)
            .filter(VerifiedLink.telegramId == telegram_id)
            .limit(1)
            .scalar()
        )
    finally:
        db.close()
    if user_id:
        delete_missing_links_for_account(user_id, references)


def list_for_user(telegram_id: int, user_id: str | None = None):
    if user_id is not None:
        return list_for_account(user_id)
    db = SessionLocal()
    try:
        return (
            db.query(VerifiedLink)
            .filter(VerifiedLink.telegramId == telegram_id)
            .order_by(VerifiedLink.reference.asc())
            .all()
        )
    finally:
        db.close()


def list_for_user_references(telegram_id: int, references: list[str], user_id: str | None = None):
    if user_id is not None:
        return list_for_account_references(user_id, references)
    normalized_references = sorted(
        {(reference or "").strip().casefold() for reference in references if (reference or "").strip()}
    )
    if not normalized_references:
        return []
    db = SessionLocal()
    try:
        return (
            db.query(VerifiedLink)
            .filter(
                VerifiedLink.telegramId == telegram_id,
                VerifiedLink.reference.in_(normalized_references),
            )
            .order_by(VerifiedLink.reference.asc())
            .all()
        )
    finally:
        db.close()
