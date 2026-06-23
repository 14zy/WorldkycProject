from datetime import datetime, timezone

from config.dbConfig import SessionLocal
from data.model.verifiedLink import VerifiedLink


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def upsert_links(telegram_id: int, user_id: str, links: list[dict]):
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


def delete_missing_links_for_user(telegram_id: int, references: set[str]):
    db = SessionLocal()
    try:
        query = db.query(VerifiedLink).filter(VerifiedLink.telegramId == telegram_id)
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
