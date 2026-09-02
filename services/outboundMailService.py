from __future__ import annotations

import logging
import json
from email.message import EmailMessage
from urllib import error, request

from config.config import (
    MAIL_FROM_DOMAIN,
    RESEND_API_KEY,
    RESEND_BASE_URL,
    RESEND_TIMEOUT_SECONDS,
)


logger = logging.getLogger(__name__)
RESEND_EMAILS_PATH = "/emails"
RESEND_USER_AGENT = "worldkycproject-mailer/1.0"


def _resend_enabled() -> bool:
    return bool(RESEND_API_KEY and MAIL_FROM_DOMAIN)


def build_forward_email(
    *,
    recipient_alias: str,
    recipient_email: str,
    sender_header: str,
    subject: str,
    body: str,
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = f"{recipient_alias.upper()}@{MAIL_FROM_DOMAIN}"
    message["To"] = recipient_email
    message["Subject"] = subject
    if sender_header:
        message["Reply-To"] = sender_header
    message.set_content(body)
    return message


def _build_resend_payload(message: EmailMessage) -> dict[str, object]:
    payload: dict[str, object] = {
        "from": message["From"],
        "to": [message["To"]],
        "subject": message["Subject"],
        "text": message.get_body(preferencelist=("plain",)).get_content(),
    }
    if message["Reply-To"]:
        payload["reply_to"] = message["Reply-To"]
    return payload


class ResendProviderError(RuntimeError):
    def __init__(self, category: str, *, temporary: bool):
        super().__init__("Resend email submission failed")
        self.category = category
        self.temporary = temporary


def _post_resend_email(payload: dict[str, object], *, idempotency_key: str | None = None):
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{RESEND_BASE_URL}{RESEND_EMAILS_PATH}",
        data=body,
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": RESEND_USER_AGENT,
            **({"Idempotency-Key": idempotency_key} if idempotency_key else {}),
        },
        method="POST",
    )
    return request.urlopen(req, timeout=RESEND_TIMEOUT_SECONDS)


def send_forward_email(
    *,
    recipient_alias: str,
    recipient_email: str,
    sender_header: str,
    subject: str,
    body: str,
):
    if not _resend_enabled():
        raise RuntimeError("Resend forwarding is not configured")

    message = build_forward_email(
        recipient_alias=recipient_alias,
        recipient_email=recipient_email,
        sender_header=sender_header,
        subject=subject,
        body=body,
    )
    payload = _build_resend_payload(message)

    try:
        _post_resend_email(payload)
    except error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace").strip()
        if response_body:
            raise RuntimeError(f"Resend request failed: {exc.code} {response_body}") from exc
        raise RuntimeError(f"Resend request failed: {exc.code}") from exc
    except error.URLError as exc:
        reason = exc.reason if exc.reason is not None else exc
        raise RuntimeError(f"Resend request failed: {reason}") from exc
    except OSError as exc:
        raise RuntimeError(f"Resend request failed: {exc}") from exc
    logger.info("Forwarded alias email alias=%s to=%s", recipient_alias, recipient_email)


def send_vmail_email(
    *,
    from_address: str,
    to_address: str,
    subject: str,
    text: str,
    idempotency_key: str,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> str:
    if not _resend_enabled():
        raise ResendProviderError("not_configured", temporary=True)

    payload: dict[str, object] = {
        "from": from_address,
        "to": [to_address],
        "subject": subject,
        "text": text,
    }
    headers = {}
    if in_reply_to:
        headers["In-Reply-To"] = in_reply_to
    if references:
        headers["References"] = references
    if headers:
        payload["headers"] = headers

    try:
        response = _post_resend_email(payload, idempotency_key=idempotency_key)
        try:
            response_body = response.read()
        finally:
            response.close()
        result = json.loads(response_body.decode("utf-8"))
        resend_email_id = result.get("id") if isinstance(result, dict) else None
        if not isinstance(resend_email_id, str) or not resend_email_id.strip():
            raise ResendProviderError("invalid_response", temporary=True)
        return resend_email_id.strip()
    except ResendProviderError:
        raise
    except error.HTTPError as exc:
        # Provider bodies can contain implementation details and are deliberately not propagated.
        temporary = exc.code == 429 or exc.code >= 500
        raise ResendProviderError(f"http_{exc.code}", temporary=temporary) from exc
    except (error.URLError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResendProviderError("transport", temporary=True) from exc
