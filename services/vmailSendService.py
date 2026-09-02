from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from email import policy
from email.parser import HeaderParser

import data.repository.outboundVmailMessageRepository as outboundRepository
import data.repository.verifiedLinkRepository as verifiedLinkRepository
from config.config import (
    MAIL_FROM_DOMAIN,
    VMAIL_ACCOUNT_SEND_LIMIT_PER_HOUR,
    VMAIL_LINK_SEND_LIMIT_PER_HOUR,
)
from services.outboundMailService import ResendProviderError, send_vmail_email


CLIENT_REQUEST_ID_RE = re.compile(r"^[0-9a-f]{32}$")
REFERENCE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
MESSAGE_ID_RE = re.compile(r"^<[^<>\s@]+@[^<>\s@]+>$")
MESSAGE_ID_SEARCH_RE = re.compile(r"<[^<>\s@]+@[^<>\s@]+>")


class VmailSendError(ValueError):
    status = 400


class VmailNotFoundError(VmailSendError):
    status = 404


class VmailConflictError(VmailSendError):
    status = 409


class VmailUnprocessableError(VmailSendError):
    status = 422


class VmailRateLimitError(VmailSendError):
    status = 429


class VmailSubmissionInProgressError(VmailSendError):
    status = 503


@dataclass(frozen=True)
class DerivedMessage:
    reference: str
    original_message_id: int | None
    to_address: str
    subject: str
    text: str
    in_reply_to: str | None = None
    references: str | None = None


def _required_string(payload: dict, name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str):
        raise VmailSendError(f"{name} is required")
    return value


def validate_client_request_id(payload: dict) -> str:
    value = _required_string(payload, "clientRequestId")
    if not CLIENT_REQUEST_ID_RE.fullmatch(value):
        raise VmailSendError("clientRequestId must be 32 lowercase hexadecimal characters")
    return value


def _validate_text(payload: dict) -> str:
    value = _required_string(payload, "text").strip()
    if not value:
        raise VmailSendError("text is required")
    if len(value) > 10_000:
        raise VmailSendError("text must not exceed 10000 characters")
    return value


def _parse_mailbox(value: str, *, allow_display_name: bool) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 320 or "\r" in value or "\n" in value:
        raise ValueError("invalid mailbox")
    try:
        header = HeaderParser(policy=policy.default).parsestr(f"To: {value}\n\n")["To"]
        addresses = tuple(header.addresses)
    except (AttributeError, ValueError):
        raise ValueError("invalid mailbox") from None
    if getattr(header, "defects", ()) or len(addresses) != 1:
        raise ValueError("invalid mailbox")
    address = addresses[0]
    if not address.username or not address.domain or any(char.isspace() for char in address.addr_spec):
        raise ValueError("invalid mailbox")
    if not allow_display_name and value.strip().casefold() != address.addr_spec.casefold():
        raise ValueError("invalid mailbox")
    return address.addr_spec


def _active_owned_link(user_id: str, reference: str):
    links = verifiedLinkRepository.list_for_account_references(user_id, [reference])
    if len(links) != 1 or (links[0].status or "").strip().casefold() != "active":
        raise VmailNotFoundError("VMail resource not found")
    return links[0]


def derive_compose(user_id: str, payload: dict) -> DerivedMessage:
    reference = _required_string(payload, "reference").strip().casefold()
    if not reference or not REFERENCE_RE.fullmatch(reference):
        raise VmailSendError("reference is invalid")
    _active_owned_link(user_id, reference)
    try:
        to_address = _parse_mailbox(_required_string(payload, "to"), allow_display_name=False)
    except ValueError as exc:
        raise VmailSendError("to must be one valid mailbox") from exc
    raw_subject = _required_string(payload, "subject")
    if "\r" in raw_subject or "\n" in raw_subject:
        raise VmailSendError("subject contains invalid characters")
    subject = raw_subject.strip()
    if not subject or len(subject) > 200:
        raise VmailSendError("subject is required and must not exceed 200 characters")
    return DerivedMessage(
        reference=reference,
        original_message_id=None,
        to_address=to_address,
        subject=subject,
        text=_validate_text(payload),
    )


def derive_reply(user_id: str, message_id: int, payload: dict) -> DerivedMessage:
    original = outboundRepository.find_owned_inbound(message_id, user_id)
    if original is None:
        raise VmailNotFoundError("VMail resource not found")
    reference = (original.recipient_alias or "").strip().casefold()
    if not REFERENCE_RE.fullmatch(reference):
        raise VmailNotFoundError("VMail resource not found")
    _active_owned_link(user_id, reference)
    to_address = None
    for destination in (original.reply_to, original.from_header):
        if not destination:
            continue
        try:
            to_address = _parse_mailbox(destination, allow_display_name=True)
            break
        except ValueError:
            continue
    if to_address is None:
        raise VmailUnprocessableError("Original message has no safe reply destination")
    rfc_message_id = (original.message_id or "").strip()
    if not MESSAGE_ID_RE.fullmatch(rfc_message_id):
        raise VmailUnprocessableError("Original message has no safe RFC Message-ID")
    subject = (original.subject or "").strip()
    if not subject or "\r" in subject or "\n" in subject:
        raise VmailUnprocessableError("Original message has no safe subject")
    if not re.match(r"^re:", subject, flags=re.IGNORECASE):
        subject = f"Re: {subject}"
    subject = subject[:200]
    references = MESSAGE_ID_SEARCH_RE.findall(original.references or "")
    if rfc_message_id not in references:
        references.append(rfc_message_id)
    return DerivedMessage(
        reference=reference,
        original_message_id=original.id,
        to_address=to_address,
        subject=subject,
        text=_validate_text(payload),
        in_reply_to=rfc_message_id,
        references=" ".join(dict.fromkeys(references)),
    )


def _payload_hash(kind: str, derived: DerivedMessage) -> str:
    normalized = json.dumps(
        {"kind": kind, **derived.__dict__},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _check_rate_limit(user_id: str, reference: str) -> None:
    if outboundRepository.count_recent(user_id=user_id) >= VMAIL_ACCOUNT_SEND_LIMIT_PER_HOUR:
        raise VmailRateLimitError("VMail sending rate limit exceeded")
    if outboundRepository.count_recent(user_id=user_id, reference=reference) >= VMAIL_LINK_SEND_LIMIT_PER_HOUR:
        raise VmailRateLimitError("VMail sending rate limit exceeded")


def submit(*, user_id: str, client_request_id: str, kind: str, derived: DerivedMessage, correlation_id: str):
    payload_hash = _payload_hash(kind, derived)
    existing = outboundRepository.find_by_request(user_id, client_request_id)
    if existing is not None:
        if existing.payload_hash != payload_hash:
            raise VmailConflictError("clientRequestId was already used for different content")
        if existing.status in {"queued", "sent", "delivered", "bounced", "complained", "delayed", "failed"}:
            return existing
        if existing.status == "submitting":
            raise VmailSubmissionInProgressError("VMail submission is already in progress")
        record, claimed = outboundRepository.retry_failed(existing.id, correlation_id)
        if not claimed:
            if record is not None and record.status in {
                "queued", "sent", "delivered", "bounced", "complained", "delayed", "failed"
            }:
                return record
            raise VmailSubmissionInProgressError("VMail submission is already in progress")
    else:
        _check_rate_limit(user_id, derived.reference)
        from_address = f"{derived.reference}@{MAIL_FROM_DOMAIN}"
        record, created = outboundRepository.create_submission(
            userId=user_id,
            reference=derived.reference,
            original_message_id=derived.original_message_id,
            client_request_id=client_request_id,
            payload_hash=payload_hash,
            from_address=from_address,
            to_address=derived.to_address,
            subject=derived.subject,
            body_text=derived.text,
            in_reply_to=derived.in_reply_to,
            references=derived.references,
            correlation_id=correlation_id,
        )
        if not created:
            if record.payload_hash != payload_hash:
                raise VmailConflictError("clientRequestId was already used for different content")
            if record.status != "submission_failed":
                raise VmailSubmissionInProgressError("VMail submission is already in progress")
            record, claimed = outboundRepository.retry_failed(record.id, correlation_id)
            if not claimed:
                raise VmailSubmissionInProgressError("VMail submission is already in progress")

    account_key = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:24]
    try:
        resend_email_id = send_vmail_email(
            from_address=record.from_address,
            to_address=record.to_address,
            subject=record.subject,
            text=record.body_text,
            in_reply_to=record.in_reply_to,
            references=record.references,
            idempotency_key=f"vmail:{account_key}:{client_request_id}",
        )
    except ResendProviderError as exc:
        outboundRepository.mark_failed(record.id, exc.category)
        raise
    return outboundRepository.mark_queued(record.id, resend_email_id)
