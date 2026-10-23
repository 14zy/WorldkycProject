from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from config.config import IMAP_USERNAME, MAIL_FROM_DOMAIN, MAIL_INBOUND_DOMAINS, VMAIL_RESERVED_LOCAL_PARTS
from config.dbConfig import SessionLocal
from data.model.verifiedLink import VerifiedLink


logger = logging.getLogger(__name__)
MAILBOX_LOCAL_PART_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
ACTIVE_STATUS = "active"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_mailbox(value) -> str:
    return value.strip().casefold() if isinstance(value, str) else ""


def reserved_mailbox_names() -> frozenset[str]:
    system_name = normalize_mailbox(IMAP_USERNAME.partition("@")[0]) if IMAP_USERNAME else ""
    return frozenset({*VMAIL_RESERVED_LOCAL_PARTS, system_name} - {""})


def normalize_mailbox_alias(value) -> str | None:
    normalized = normalize_mailbox(value)
    if not normalized or not MAILBOX_LOCAL_PART_RE.fullmatch(normalized):
        return None
    if normalized in reserved_mailbox_names():
        return None
    return normalized


def normalize_mailbox_domain(value) -> str | None:
    normalized = value.strip().casefold().removeprefix("@").rstrip(".") if isinstance(value, str) else ""
    return normalized if normalized in MAIL_INBOUND_DOMAINS else None


def _mailbox_alias_from_link(link: dict) -> str | None:
    for key in ("mailboxAlias", "selectedAccountAlias", "SelectedAccountAlias"):
        if key in link:
            return normalize_mailbox_alias(link.get(key))
    return None


def _link_reference(link: dict) -> str:
    return normalize_mailbox(link.get("verifiedLinkReference") or link.get("reference"))


def sync_links_for_user(user_id: str, links: list[dict], telegram_id: int | None = None):
    """Atomically replace one account's synchronized VLinks and alias mappings."""
    db = SessionLocal()
    warnings: list[dict[str, str]] = []
    try:
        now = _utcnow()
        normalized_items: dict[str, tuple[dict, str | None, str]] = {}
        incoming_references: set[str] = set()
        existing_domains = dict(
            db.query(VerifiedLink.reference, VerifiedLink.mailboxDomain)
            .filter(VerifiedLink.userId == user_id)
            .all()
        )
        for link in links:
            reference = _link_reference(link)
            if not reference or not MAILBOX_LOCAL_PART_RE.fullmatch(reference):
                continue
            incoming_references.add(reference)
            raw_alias = next(
                (link.get(key) for key in ("mailboxAlias", "selectedAccountAlias", "SelectedAccountAlias") if key in link),
                None,
            )
            alias = _mailbox_alias_from_link(link)
            raw_domain = link.get("mailboxDomain") or link.get("domainAlias") or link.get("DomainAlias")
            domain = normalize_mailbox_domain(raw_domain)
            if normalize_mailbox(raw_alias) and alias is None:
                warnings.append({"reference": reference, "mailboxAlias": normalize_mailbox(raw_alias), "reason": "invalid_or_reserved"})
            if normalize_mailbox(raw_domain) and domain is None:
                warnings.append({"reference": reference, "mailboxDomain": normalize_mailbox(raw_domain), "reason": "unsupported_domain"})
            normalized_items[reference] = (
                link,
                alias,
                domain or existing_domains.get(reference) or MAIL_FROM_DOMAIN,
            )

        # References omitted from this account's snapshot are deleted below and
        # must not temporarily block an alias taking over that namespace.
        reference_domains = {
            (reference, domain or MAIL_FROM_DOMAIN)
            for reference, domain, owner in db.query(
                VerifiedLink.reference,
                VerifiedLink.mailboxDomain,
                VerifiedLink.userId,
            ).all()
            if owner != user_id or reference in incoming_references
        } | {
            (reference, domain)
            for reference, (_link, _alias, domain) in normalized_items.items()
        }
        requested_aliases = {(alias, domain) for _, alias, domain in normalized_items.values() if alias}
        foreign_alias_owners: dict[tuple[str, str], set[str]] = {}
        if requested_aliases:
            alias_names = {alias for alias, _domain in requested_aliases}
            domains = {domain for _alias, domain in requested_aliases}
            for alias, domain, owner in (
                db.query(VerifiedLink.mailboxAlias, VerifiedLink.mailboxDomain, VerifiedLink.userId)
                .filter(
                    VerifiedLink.mailboxAlias.in_(alias_names),
                    VerifiedLink.mailboxDomain.in_(domains),
                    VerifiedLink.userId != user_id,
                )
                .all()
            ):
                foreign_alias_owners.setdefault((alias, domain), set()).add(owner)

        for reference, (link, alias, domain) in normalized_items.items():
            if alias and (alias, domain) in reference_domains:
                warnings.append({"reference": reference, "mailboxAlias": alias, "reason": "vlink_reference_collision"})
                alias = None
            elif alias and (alias, domain) in foreign_alias_owners:
                warnings.append({"reference": reference, "mailboxAlias": alias, "reason": "cross_account_collision"})
                alias = None

            existing = db.query(VerifiedLink).filter(VerifiedLink.reference == reference).first()
            if existing is not None and existing.userId != user_id:
                warnings.append({"reference": reference, "mailboxAlias": alias or "", "reason": "reference_owned_by_another_account"})
                continue
            if existing is None:
                existing = VerifiedLink(reference=reference, userId=user_id, updatedAt=now)
                db.add(existing)

            existing.telegramId = telegram_id
            existing.userId = user_id
            existing.name = link.get("verifiedLinkName") or link.get("name")
            existing.status = link.get("verifiedLinkStatusTypeName") or link.get("statusTypeName") or link.get("status")
            existing.mailboxAlias = alias
            existing.mailboxDomain = domain
            existing.updatedAt = now

        delete_query = db.query(VerifiedLink).filter(VerifiedLink.userId == user_id)
        if incoming_references:
            delete_query = delete_query.filter(VerifiedLink.reference.notin_(incoming_references))
        delete_query.delete(synchronize_session=False)
        db.commit()
        for warning in warnings:
            logger.warning("VLink mailbox alias not routed userId=%s details=%s", user_id, warning)
        return incoming_references, warnings
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def upsert_links_for_user(user_id: str, links: list[dict], telegram_id: int | None = None):
    references, _warnings = sync_links_for_user(user_id, links, telegram_id=telegram_id)
    return references


def delete_missing_links_for_account(user_id: str, references: set[str]):
    # Transitional API retained for older callers. New sync callers use the atomic function above.
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


def find_by_reference(reference: str, domain: str | None = None):
    normalized_reference = normalize_mailbox(reference)
    if not normalized_reference:
        return None
    db = SessionLocal()
    try:
        query = db.query(VerifiedLink).filter(VerifiedLink.reference == normalized_reference)
        if domain is not None:
            normalized_domain = normalize_mailbox_domain(domain)
            if not normalized_domain:
                return None
            query = query.filter(VerifiedLink.mailboxDomain == normalized_domain)
        return query.first()
    finally:
        db.close()


def list_active_by_mailbox_alias(alias: str, domain: str | None = None):
    normalized_alias = normalize_mailbox_alias(alias)
    if not normalized_alias:
        return []
    db = SessionLocal()
    try:
        reference_query = db.query(VerifiedLink.reference).filter(VerifiedLink.reference == normalized_alias)
        if domain is not None:
            normalized_domain = normalize_mailbox_domain(domain)
            if not normalized_domain:
                return []
            reference_query = reference_query.filter(VerifiedLink.mailboxDomain == normalized_domain)
        else:
            normalized_domain = None
        if reference_query.first():
            logger.error("Alias namespace collides with VLink reference alias=%s", normalized_alias)
            return []
        query = db.query(VerifiedLink).filter(
                VerifiedLink.mailboxAlias == normalized_alias,
                VerifiedLink.status.ilike(ACTIVE_STATUS),
            )
        if domain is not None:
            query = query.filter(VerifiedLink.mailboxDomain == normalized_domain)
        links = (
            query
            .order_by(VerifiedLink.reference.asc())
            .all()
        )
        owners = {link.userId for link in links}
        if len(owners) > 1:
            logger.error("Cross-account mailbox alias collision quarantined alias=%s owners=%s", normalized_alias, sorted(owners))
            return []
        return links
    finally:
        db.close()


def list_active_for_account_mailbox(user_id: str, mailbox: str, domain: str | None = None):
    normalized = normalize_mailbox(mailbox)
    if not normalized:
        return []
    db = SessionLocal()
    try:
        direct_query = db.query(VerifiedLink).filter(
                VerifiedLink.userId == user_id,
                VerifiedLink.reference == normalized,
                VerifiedLink.status.ilike(ACTIVE_STATUS),
            )
        normalized_domain = normalize_mailbox_domain(domain) if domain is not None else None
        if domain is not None and not normalized_domain:
            return []
        if normalized_domain:
            direct_query = direct_query.filter(VerifiedLink.mailboxDomain == normalized_domain)
        direct = direct_query.all()
    finally:
        db.close()
    if direct:
        return direct
    return [link for link in list_active_by_mailbox_alias(normalized, normalized_domain) if link.userId == user_id]


def list_for_account(user_id: str):
    db = SessionLocal()
    try:
        return db.query(VerifiedLink).filter(VerifiedLink.userId == user_id).order_by(VerifiedLink.reference.asc()).all()
    finally:
        db.close()


def list_for_account_references(user_id: str, references: list[str]):
    normalized_references = sorted({normalize_mailbox(reference) for reference in references if normalize_mailbox(reference)})
    if not normalized_references:
        return []
    db = SessionLocal()
    try:
        return (
            db.query(VerifiedLink)
            .filter(VerifiedLink.userId == user_id, VerifiedLink.reference.in_(normalized_references))
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
        user_id = db.query(VerifiedLink.userId).filter(VerifiedLink.telegramId == telegram_id).limit(1).scalar()
    finally:
        db.close()
    if user_id:
        delete_missing_links_for_account(user_id, references)


def list_for_user(telegram_id: int, user_id: str | None = None):
    if user_id is not None:
        return list_for_account(user_id)
    db = SessionLocal()
    try:
        return db.query(VerifiedLink).filter(VerifiedLink.telegramId == telegram_id).order_by(VerifiedLink.reference.asc()).all()
    finally:
        db.close()


def list_for_user_references(telegram_id: int, references: list[str], user_id: str | None = None):
    if user_id is not None:
        return list_for_account_references(user_id, references)
    normalized_references = sorted({normalize_mailbox(reference) for reference in references if normalize_mailbox(reference)})
    if not normalized_references:
        return []
    db = SessionLocal()
    try:
        return (
            db.query(VerifiedLink)
            .filter(VerifiedLink.telegramId == telegram_id, VerifiedLink.reference.in_(normalized_references))
            .order_by(VerifiedLink.reference.asc())
            .all()
        )
    finally:
        db.close()
