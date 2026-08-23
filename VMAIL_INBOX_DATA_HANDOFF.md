# WorldkycProject Handoff: Add VMail Inbox Data

## Purpose

The WKYC Blazor page `WKYC_web/Components/Pages/VerifiedEmail.razor` can already display VLink email controls, but its "Latest e-mails" section is still mock data. The Python `WorldkycProject` already has the right foundation for alias sync and idempotent inbound mail processing. The missing piece is durable VMail inbox data and an API endpoint that the Blazor app can query.

This document is for the developer working in the sibling Python project:

```text
../WorldkycProject
```

## Current State

Already present in `WorldkycProject`:

- Alembic setup:
  - `alembic.ini`
  - `alembic/env.py`
- VLink cache migration:
  - `alembic/versions/20250622_0002_verified_links_and_processed_emails.py`
- SQLAlchemy models:
  - `data/model/verifiedLink.py`
  - `data/model/processedEmail.py`
- Repositories:
  - `data/repository/verifiedLinkRepository.py`
  - `data/repository/processedEmailRepository.py`
- VLink sync:
  - `services/vlinkSyncService.py`
- IMAP ingress, alias extraction, sanitization, forwarding, and idempotency:
  - `services/mailService.py`
- TMA route registration:
  - `controller/tmaController.py`

The existing `processed_emails` table records processing status and enforces unique `(mailbox, imap_uid)`. It does not store message content for an inbox UI.

## Missing Backend Feature

Add persisted VMail inbox messages that can be read by a UI.

The Blazor page needs real data replacing this mock method:

```text
WKYC_web/Components/Pages/VerifiedEmail.razor -> BuildPreviewEmails(...)
```

The Python project should store one inbox message per delivered alias target and expose a query endpoint returning messages grouped/filterable by VLink reference.

## Proposed Table

Create an Alembic migration for `vmail_messages`.

Recommended columns:

```text
vmail_messages
- id                  integer primary key autoincrement
- mailbox             string not null
- imap_uid            string not null
- message_id          string nullable
- recipient_alias     string not null
- telegramId          bigint nullable
- userId              string nullable
- from_header         string not null
- reply_to            string nullable
- subject             string not null
- snippet             string not null
- body_text           text not null
- sender_trust        string not null default 'anonymous'
- notary_status       string nullable
- identity_status     string nullable
- governance_status   string nullable
- delivery_status     string not null
- receivedAt          timestamptz nullable
- processedAt         timestamptz not null
- is_read             boolean not null default false
- error               string nullable
```

Recommended constraints and indexes:

```text
Unique: mailbox + imap_uid + recipient_alias
Index: recipient_alias
Index: telegramId
Index: userId
Index: delivery_status
Index: processedAt
Index: receivedAt
Index: message_id
```

Use lowercase/casefolded `recipient_alias`, matching the existing `verified_links.reference` convention.

## SQLAlchemy Model

Add:

```text
data/model/vmailMessage.py
```

The model should use the same `Base` from `config/dbConfig.py`.

Suggested class name:

```python
class VMailMessage(Base):
    __tablename__ = "vmail_messages"
```

Also import the model in `alembic/env.py` so Alembic metadata sees it.

## Repository

Add:

```text
data/repository/vmailMessageRepository.py
```

Minimum functions:

```python
def upsert_from_processed_message(
    *,
    mailbox: str,
    imap_uid: str,
    message_id: str | None,
    recipient_alias: str,
    telegram_id: int | None,
    user_id: str | None,
    from_header: str,
    reply_to: str | None,
    subject: str,
    body_text: str,
    delivery_status: str,
    error: str | None = None,
):
    ...
```

```python
def list_for_aliases(
    aliases: list[str],
    *,
    limit: int = 25,
    offset: int = 0,
    unread_only: bool = False,
):
    ...
```

```python
def mark_read(message_id: int, *, telegram_id: int | None = None, user_id: str | None = None):
    ...
```

The insert/update should be idempotent using `(mailbox, imap_uid, recipient_alias)`.

## Mail Ingress Change

Update `services/mailService.py` inside `_process_message`.

When a message resolves to a verified alias and is delivered or partially delivered, store an inbox row after the delivery attempt.

Use existing helpers where possible:

- `_decode_header_value(...)`
- `_extract_body(...)`
- `sanitize_mail_text(...)`
- `_build_plain_forward_content(...)`

Suggested fields:

```text
from_header: sanitized decoded From header, fallback "(unknown sender)"
reply_to: sanitized Reply-To header if present, otherwise From address/header
subject: sanitized decoded Subject, fallback "(no subject)"
body_text: sanitized extracted body, fallback "(empty message)"
snippet: first 160-240 chars of body_text, normalized for one-line display
delivery_status: delivered, telegram_only, partial, or error
processedAt: now UTC
receivedAt: parsed Date header when valid, otherwise null
```

Do not store raw HTML for the first version. Store sanitized text only.

## API Endpoint

Add routes in `controller/tmaController.py`.

Recommended endpoints:

```text
GET /api/tma/vmail/messages
POST /api/tma/vmail/messages/{id}/read
```

Authentication should use the same `X-Telegram-Init-Data` flow as existing TMA GET routes.

### GET Query Parameters

```text
references=vl10776,vl10777
limit=25
offset=0
unreadOnly=false
```

If `references` is omitted, return messages for all locally cached VLinks owned by the linked user.

Important authorization rule:

```text
The authenticated user can only read messages for aliases tied to their own linked user/telegramId.
```

### GET Response Shape

Return JSON that is easy for the Blazor app to map.

```json
{
  "messages": [
    {
      "id": 123,
      "reference": "vl10776",
      "from": "Compliance Desk <review@example-bank.com>",
      "replyTo": "review@example-bank.com",
      "subject": "Additional information requested",
      "receivedAt": "2026-08-14T03:20:00Z",
      "receivedLabel": "2h ago",
      "deliveryStatus": "delivered",
      "isUnread": true,
      "snippet": "Please confirm the beneficiary details...",
      "bodyPreview": "Please confirm the beneficiary details attached to your verified link...",
      "senderTrust": "verified",
      "notaryStatus": "World KYC HK",
      "identityStatus": "Verified",
      "governanceStatus": "Approved"
    }
  ],
  "limit": 25,
  "offset": 0
}
```

For the first implementation, `senderTrust`, `notaryStatus`, `identityStatus`, and `governanceStatus` can use conservative defaults:

```text
senderTrust: anonymous
notaryStatus: N/A
identityStatus: Not disclosed
governanceStatus: Review required
```

These can be upgraded later when real trust/notary checks exist.

## Blazor Integration Contract

The Blazor page should keep using `VerifiedLinkSearchAsync(...)` for VLinks.

After the Python endpoint exists, the C# side can:

1. Load VLinks as it does today.
2. Build the alias/reference list from loaded VLinks.
3. Call the Python VMail endpoint.
4. Attach returned messages to each `VerifiedLinkEmailControlDto` by `reference`.
5. Remove or fallback-gate `BuildPreviewEmails(...)`.

Do not make the Blazor page read PostgreSQL directly for the first version. Keep PostgreSQL behind the Python service because the Python project owns IMAP processing and normalization.

## Acceptance Criteria

The Python backend work is complete when:

- Alembic creates `vmail_messages`.
- IMAP processing stores sanitized message rows for matched VLink aliases.
- Duplicate IMAP deliveries do not create duplicate inbox rows.
- Message rows are linked to lowercase `recipient_alias`.
- The API returns only messages authorized for the current linked user.
- The API supports querying by one or more VLink references.
- The API response contains enough fields to replace `BuildPreviewEmails(...)`.
- Tests cover storage, duplicate handling, authorization filtering, and response shape.

## Suggested Tests

Add tests near the existing mail tests:

```text
tests/test_vmail_messages.py
```

Recommended coverage:

- Store a delivered message for `VL10776@tonstealthid.com` as `vl10776`.
- Upsert same `(mailbox, imap_uid, recipient_alias)` without duplicating.
- Store separate rows for the same IMAP UID when two different aliases resolve to different users.
- Do not return messages for another user's alias.
- Return messages sorted newest first.
- Convert HTML-only emails to sanitized text before storage.
- Preserve subject, from, reply-to, delivery status, and body preview.

## Implementation Notes

Keep `processed_emails` as the idempotent processing ledger. Add `vmail_messages` as the user-facing inbox projection.

The lifecycle should be:

```text
WorldKYC VLink sync
-> verified_links.reference
-> inbound email recipient alias
-> process/forward message
-> processed_emails ledger row
-> vmail_messages inbox row
-> Blazor VerifiedEmail.razor display
```

The generated address remains derived data:

```text
{reference}@tonstealthid.com
```

Do not store generated alias email as the source of truth. Store and query by normalized `reference` / `recipient_alias`.
