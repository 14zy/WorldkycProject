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


def _post_resend_email(payload: dict[str, object]):
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{RESEND_BASE_URL}{RESEND_EMAILS_PATH}",
        data=body,
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": RESEND_USER_AGENT,
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
