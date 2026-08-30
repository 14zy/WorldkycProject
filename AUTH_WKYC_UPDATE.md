# WorldKYC authentication and Telegram migration

## Decision

WorldKYC `UserId` becomes the canonical identity for VLinks and VMail. Telegram remains a supported authentication and notification channel, but a Telegram account is an optional link to a WorldKYC account rather than the owner of the data.

The migration will be performed during a planned 1–2 hour maintenance window. The services do not need to support the old and new authentication models simultaneously while the migration is running. Existing Telegram users and their data must work again when maintenance ends.

## Target architecture

```text
                         +----------------------+
WKYC browser session --->| WKYC same-origin API |--- signed assertion ---+
                         +----------------------+                        |
                                                                          v
Telegram initData ---> TelegramLink ---> WorldKycAccount ---> VLinks / VMail
                                                                          ^
Telegram connect code ---------------- WKYC browser session ---------------+
```

WorldKYC credentials are entered only on the WKYC login page. Telegram `initData` proves control of a Telegram account; it is not a WorldKYC login.

### Canonical data model

```text
WorldKycAccount
- userId (unique canonical identity)
- emailAddress
- createdAt
- updatedAt

TelegramLink
- telegramId (unique)
- userId (foreign key to WorldKycAccount)
- linkedAt
- revokedAt

VerifiedLink
- reference
- userId (foreign key to WorldKycAccount)
- name
- status
- updatedAt

VMailMessage
- ...
- userId (owner)
- telegramId (optional delivery/audit metadata during transition)
```

One WorldKYC account may have one or more Telegram links if product policy allows it. A Telegram ID can have only one active WorldKYC account link.

## Authentication flows

### WKYC website

1. The user signs in through the normal WKYC login page.
2. WKYC keeps the WorldKYC access/refresh session server-side.
3. The browser calls same-origin WKYC endpoints such as `/api/vmail/messages`.
4. WKYC calls TMA server-to-server with a short-lived signed assertion.
5. TMA authorizes the request by the assertion's `sub` WorldKYC `UserId`.

The browser must never receive TMA service credentials, private signing material, or WorldKYC refresh tokens.

Cutover note: WKYC currently stores WorldKYC tokens inside its protected authentication ticket. Moving them to an opaque server-side session is still the target. If that larger session change is deferred, the first cutover may temporarily keep the existing protected, `HttpOnly`, `Secure` authentication cookie, provided tokens are never returned to JavaScript, markup, API responses, or logs. The assertion must still be minted only on the WKYC server.

The assertion must contain:

- `iss`: configured WKYC issuer
- `sub`: WorldKYC `UserId`
- `aud`: exact TMA audience, initially `worldkyc-tma`
- `scope`: endpoint-specific permissions such as `vlinks.read`, `vmail.read`, or `vmail.write`
- `iat` and `nbf`
- `exp`: no more than five minutes after issuance
- `jti`: unique assertion ID

TMA must use an asymmetric signature, an explicit algorithm allowlist, exact issuer/audience validation, small clock-skew tolerance, and key rotation through a configured key ID/public key set. Mutating operations must have replay protection where appropriate.

The current mutations are either idempotent (VLink replacement and mark-read) or protected by a separately stored single-use code (Telegram redemption). If a future assertion authorizes a non-idempotent operation, TMA must persist/consume its `jti` for the assertion lifetime.

### Telegram Mini App and inline mode

1. TMA validates the Telegram `initData` signature and rejects missing, malformed, future, or stale `auth_date` values.
2. TMA resolves `telegramId -> active TelegramLink -> WorldKycAccount.userId`.
3. TMA authorizes locally stored VLinks and VMail by `userId`.
4. Telegram inline VLink results use the account-owned VLink cache. They must not require TMA-held WorldKYC access/refresh tokens.

Existing Telegram users are linked automatically by the maintenance migration. They must not be asked to reconnect after the deployment.

### Connecting a new Telegram account

1. TMA validates Telegram `initData` and creates a cryptographically random connection code.
2. TMA stores only a hash of the code, bound server-side to the Telegram ID, with an expiry of approximately five minutes.
3. Telegram opens `wkyc.example/connect-telegram?code=...`.
4. The user signs in on WKYC if necessary.
5. WKYC redeems the code through a signed server-to-server request identifying the authenticated WorldKYC `UserId`.
6. TMA atomically consumes the code and creates the Telegram link.

Codes are single-use. Relinking a Telegram ID already attached to another account requires an explicit authenticated unlink/takeover flow; a connection-code request must never silently replace it.

“Log out of WKYC” and “Unlink Telegram” are separate operations.

## VLink synchronization

TMA currently refreshes VLinks with WorldKYC access/refresh tokens stored against Telegram users. That mechanism must be replaced before maintenance ends.

WKYC should push the authenticated account's current VLink set to a signed TMA synchronization endpoint, or provide a narrowly scoped delegated service endpoint. Synchronization and deletion operate by WorldKYC `userId`, never by Telegram ID.

The locally synchronized VLink set is used for:

- Telegram Mini App VLink lists
- Telegram inline results
- VMail alias ownership and delivery routing
- WKYC VMail authorization

## TMA server-to-server API contract

WKYC sends the signed assertion as `Authorization: Bearer <assertion>`.

```text
GET  /api/internal/v1/vlinks
      scope: vlinks.read

PUT  /api/internal/v1/vlinks
      scope: vlinks.sync
      body: { "items": [ ...WorldKYC VLink objects... ] }

GET  /api/internal/v1/vmail/messages?references=...&limit=...&offset=...&unreadOnly=...
      scope: vmail.read

POST /api/internal/v1/vmail/messages/{id}/read
      scope: vmail.write

POST /api/internal/v1/telegram-links/redeem
      scope: telegram.link
      body: { "code": "single-use connection code" }
```

The assertion subject is the only accepted account identity. TMA ignores client-provided `userId` values.

### Response and error contract

Successful VLink responses use:

```json
{
  "items": [
    {
      "id": "vl10776",
      "reference": "vl10776",
      "name": "Example VLink",
      "status": "Active",
      "url": "https://app.worldkyc.com/vl/vl10776"
    }
  ]
}
```

Successful inbox responses use `{ "messages": [...] }`. Message objects retain the existing WKYC/TMA fields: `id`, `reference`, `from`, `replyTo`, `subject`, `receivedAt`, `receivedLabel`, `deliveryStatus`, `isUnread`, `snippet`, `bodyPreview`, `senderTrust`, `notaryStatus`, `identityStatus`, and `governanceStatus`.

The read endpoint returns `{ "message": {...} }`. Telegram redemption returns:

```json
{ "linked": true, "telegramId": 123456789, "userId": "<WorldKYC UserId>" }
```

Expected failures:

- `400`: malformed query/body
- `401`: missing, invalid, expired, incorrectly scoped, or incorrectly signed assertion
- `404`: account has not been synchronized, or the requested message is not owned by the assertion subject
- `409`: invalid/expired/used Telegram code, or Telegram is already linked to another account

WKYC must not forward TMA error details directly to the public UI. Log a correlation ID and a sanitized status/message; never log the assertion, connection code, access token, refresh token, or full authentication response.

## WKYC_web implementation checklist

This section is the handoff for the WKYC_web repository.

### 1. Add configuration and signing-key handling

Add a typed server-side configuration section similar to:

```json
{
  "TmaDelegation": {
    "BaseUrl": "https://tonstealthid.com",
    "Issuer": "worldkyc-web",
    "Audience": "worldkyc-tma",
    "KeyId": "wkyc-2026-08",
    "PrivateKeyPath": "/run/secrets/wkyc-tma-signing-key.pem",
    "AssertionLifetimeSeconds": 120,
    "TimeoutSeconds": 15
  }
}
```

Requirements:

- Keep the RSA private key in the deployment secret store, never in source control or browser-accessible configuration.
- Use RS256 only and include the configured `kid` in the JWT header.
- Use an assertion lifetime between 60 and 300 seconds.
- Use UTC NumericDate values for `iat`, `nbf`, and `exp`.
- Generate a new cryptographically random `jti` for every request.
- Put the authenticated WKYC `UserId` claim into `sub`; do not accept `sub` from a request body/query string.
- Add the user's email as the optional `email` claim when available. TMA uses it to update forwarding information during VLink synchronization.
- Grant only the one scope needed by the outbound request.

Generate a key pair outside the repositories, for example:

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out wkyc-tma-private.pem
openssl pkey -in wkyc-tma-private.pem -pubout -out wkyc-tma-public.pem
```

WKYC receives the private key. TMA receives only the public key through `WKYC_ASSERTION_PUBLIC_KEYS_JSON`, keyed by the same `kid`.

For rotation: add the new public key to TMA first, deploy WKYC signing with the new `kid`, wait longer than the maximum assertion lifetime, and then remove the old public key.

### 2. Implement a delegated assertion service

Create a singleton signing-key provider and a scoped assertion factory. The factory should conceptually expose:

```text
CreateAssertion(authenticatedPrincipal, requiredScope) -> compact JWT
```

It must:

1. Reject unauthenticated principals.
2. Read the existing server-authenticated `UserId` claim (currently named `UserId`).
3. Validate that it is a non-empty WorldKYC identifier.
4. Create `iss`, `sub`, `aud`, `scope`, `iat`, `nbf`, `exp`, and `jti` claims.
5. Sign with the configured RSA private key and RS256.

Do not reuse assertions across users. Prefer creating one assertion per outbound TMA request; the signing key object itself may be cached.

### 3. Add a typed TMA server client

Create an `HttpClient` service that:

- Uses `TmaDelegation:BaseUrl` and a bounded timeout.
- Creates a fresh assertion with the exact required scope for every call.
- Sends it as `Authorization: Bearer <assertion>`.
- Uses server-side calls only; never returns the assertion to JavaScript or browser markup.
- URL-encodes query values and connection codes.
- Deserializes the response contract above.
- Treats non-success responses explicitly instead of relying on unhandled `EnsureSuccessStatusCode` exceptions.
- Does not automatically retry Telegram-code redemption or other mutations.
- Uses HTTPS in production and a fixed configured base URL; never accept a TMA base URL from a browser request.

Recommended methods:

```text
SyncVLinksAsync(principal, items)             // PUT,  vlinks.sync
GetVLinksAsync(principal)                     // GET,  vlinks.read
GetVMailMessagesAsync(principal, query)        // GET,  vmail.read
MarkVMailMessageReadAsync(principal, id)       // POST, vmail.write
RedeemTelegramCodeAsync(principal, code)       // POST, telegram.link
```

### 4. Synchronize the account before reading VMail

`GET /api/internal/v1/vlinks` and the VMail endpoints return `404` until the WorldKYC account exists in TMA. The first WKYC operation must therefore be VLink synchronization:

1. Resolve the authenticated user's current VLinks using the normal WKYC session/access token.
2. Send the complete current set to `PUT /api/internal/v1/vlinks` with `vlinks.sync`.
3. An empty `items` array is valid and removes previously cached VLinks for that user.
4. Only after successful synchronization, request VMail/VLinks from TMA.

Also synchronize after a VLink is created, renamed, reactivated, expired, transferred, or deleted. The PUT operation represents a complete replacement for that `UserId`, not a partial patch.

The VLink objects must include the fields already understood by TMA:

- `verifiedLinkReference` or `reference`
- `verifiedLinkName` or `name`
- `verifiedLinkStatusTypeName` or `statusTypeName`
- optional `verifiedLinkId` or `id`

VMail `limit` is clamped to 1–100 and `offset` to 0–10000. If the WKYC page needs more than 100 messages, request pages of 100 and continue until a page contains fewer than 100 items. A requested VLink reference not owned by `sub` is silently excluded; it never grants cross-account access.

### 5. Replace VerifiedEmail.razor's Telegram-dependent calls

In `Components/Pages/VerifiedEmail.razor`:

- Remove calls to `GetTelegramInitDataAsync`.
- Remove `ShouldUseLegacyTmaSharedLogin` and `LoginToTmaBackendAsync`.
- Do not call `/api/tma/login` or send `X-Telegram-Init-Data`.
- Remove the production static `TmaBackend:InitData` fallback.
- Load the current user's VLinks through WKYC, synchronize them with the typed TMA client, and load VMail with a `vmail.read` assertion.
- Mark messages read through the typed client with `vmail.write`.
- Preserve the existing DTO/UI mapping so Telegram and non-Telegram users see the same stored messages.

Prefer moving all TMA communication out of the Razor component into the typed service. If browser JavaScript needs an endpoint, expose a same-origin authenticated WKYC controller/minimal API that calls the service server-side.

Same-origin mutation endpoints must use the existing WKYC authorization policy plus antiforgery/CSRF protection. They must derive `UserId` from the authenticated principal, never from browser input.

### 6. Add the Telegram connection page

Add an authenticated route such as `/connect-telegram?code=...`:

1. Validate that `code` is present and no longer than 128 characters; do not log it.
2. If the user is not authenticated, redirect to the normal WKYC login with a local-only return URL back to this route.
3. After login, fetch the user's complete current VLink set and synchronize it using a fresh `vlinks.sync` assertion. This also creates an account for users with zero VLinks.
4. If synchronization succeeds, mint a separate `telegram.link` assertion for the authenticated `UserId`.
5. POST `{ "code": "..." }` to `/api/internal/v1/telegram-links/redeem` server-to-server.
6. Show a simple success page instructing the user to return to/reopen Telegram.
7. For `409`, show an expired/already-used/already-linked message without exposing account identifiers.

Set a restrictive referrer policy for this page so the connection code is not leaked through outbound navigation. Do not place the code in analytics events, logs, cookies, or local storage.

### 7. Fix current WKYC credential handling

Before deployment:

- Remove `_logger.LogInformation("authResp: ...")` serialization from `Pages/Login.cshtml.cs`; it contains sensitive authentication data.
- Remove `TmaBackend:LoginId`, `TmaBackend:Password`, `TmaBackend:EnableLegacySharedLogin`, `TmaBackend:InitData`, and `TmaBackend:AllowStaticInitDataFallback` from deployed configuration.
- Rotate any shared credentials or Telegram `initData` values that were previously deployed.

Moving WorldKYC access/refresh tokens from authentication-cookie claims to an encrypted server-side session remains recommended, but it does not have to block this maintenance cutover if it cannot be completed safely in the same window.

### 8. WKYC_web tests required before cutover

- Assertion contains the exact issuer, audience, subject, scope, timestamps, `jti`, `kid`, and RS256 signature.
- Assertion creation fails without an authenticated principal or `UserId` claim.
- Each TMA client method requests only its required scope.
- VLink synchronization sends the complete set and accepts an empty set.
- VerifiedEmail loads without Telegram JavaScript or `initData`.
- A user cannot request another user's VLinks/messages by changing query/body data.
- Read operations cannot modify a message owned by another `UserId`.
- Telegram redemption survives the login redirect, succeeds once, and handles reuse/expiry safely.
- Assertions, connection codes, passwords, and WorldKYC tokens do not appear in application logs.
- Public WKYC mutation endpoints reject unauthenticated and antiforgery-invalid requests.

## Current TMA implementation status

The WorldkycProject side already contains the implementation described by this document:

- Alembic revision `20260831_0006` creates and backfills accounts, Telegram links, and connection codes.
- `controller/wkycDelegatedController.py` implements the server-to-server endpoints.
- `utils/wkyc_assertion.py` validates scoped RS256 assertions.
- Telegram Mini App bootstrap, VLinks, VMail, and inline queries resolve account ownership through `TelegramLink`.
- The Mini App creates a connection code and sends new users to `WKYC_TELEGRAM_CONNECT_URL`.
- Mail ingress supports account-owned inbox/email delivery without a Telegram link.
- `scripts/validate_auth_cutover.py` performs post-migration ownership checks.

The legacy `/api/tma/login` and `/api/v1/auth` routes and legacy token columns remain temporarily for rollback, but the new Mini App UI does not call them. Do not build new WKYC_web code against those legacy routes.

The TMA container entrypoint automatically runs `alembic upgrade head`. For a controlled maintenance cutover, run the new image as a one-off migration/validation container before starting the long-running app, or run these commands in the prepared runtime environment:

```bash
alembic upgrade head
python -m scripts.validate_auth_cutover
```

Do not start `main.py` until validation returns `"valid": true`; `main.py` starts the HTTP server, Telegram bot, and mail ingress together.

## Maintenance-window migration

### Before shutdown

- Deploy and test the database migration against a recent production copy.
- Record row counts and orphan checks for users, VLinks, and VMail messages.
- Back up the production database and verify that the backup can be restored.
- Confirm that inbound mail will remain queued in IMAP while polling is stopped.
- Prepare a rollback build compatible with the pre-migration schema.

### During maintenance

1. Stop the WKYC VMail integration, TMA web backend, Telegram bot, mail polling, token refresh, and VLink synchronization workers.
2. Take the final database backup.
3. Create `world_kyc_accounts` and `telegram_links`.
4. Create one account per distinct non-empty legacy `users.userId`.
5. Create a Telegram link for every legacy user with a valid `telegramId` and `userId`.
6. Backfill `verified_links.userId` ownership and validate every VLink owner.
7. Preserve existing `vmail_messages.userId`; backfill it from VLink ownership where necessary.
8. Keep the legacy `users` table, token columns, and transitional Telegram columns for rollback. Do not drop them in this migration.
9. Deploy the account-based backend and WKYC proxy integration.
10. Run database validation and application smoke tests.
11. After validation succeeds, start the TMA application (HTTP server, Telegram bot, and mail ingress) and WKYC_web.
12. Monitor authorization failures, unmatched aliases, Telegram delivery errors, and message processing.

### Cutover acceptance checks

- Every legacy row with a WorldKYC `userId` has one `WorldKycAccount`.
- Every previously linked Telegram user has an active `TelegramLink` to the same `userId`.
- No VLink is missing a valid account owner.
- Existing VMail messages are visible to their original account.
- WKYC website VMail works without Telegram `initData`.
- Telegram Mini App bootstrap, VLinks, VMail, and read operations work through `TelegramLink`.
- Telegram inline VLinks work without TMA access/refresh tokens.
- A new Telegram connection code can be redeemed once and cannot be replayed.
- Stale Telegram `initData` is rejected.
- Mail accumulated during maintenance is processed exactly once after restart.

Run the automated database checks after migration and before restarting workers:

```bash
python -m scripts.validate_auth_cutover
```

The command exits non-zero if legacy Telegram links, account owners, VLink owners, or VMail owners are missing.

## Required TMA configuration

- `WKYC_ASSERTION_ISSUER`: exact WKYC assertion issuer
- `WKYC_ASSERTION_AUDIENCE`: exact TMA audience; default `worldkyc-tma`
- `WKYC_ASSERTION_PUBLIC_KEYS_JSON`: JSON object mapping signing `kid` values to PEM public keys
- `WKYC_ASSERTION_MAX_LIFETIME_SECONDS`: maximum assertion lifetime; default 300
- `WKYC_ASSERTION_CLOCK_SKEW_SECONDS`: accepted clock skew; default 30
- `WKYC_TELEGRAM_CONNECT_URL`: WKYC browser endpoint used to redeem Telegram codes
- `TELEGRAM_CONNECT_CODE_TTL_SECONDS`: connection code lifetime; default 300
- `TELEGRAM_INIT_DATA_MAX_AGE_SECONDS`: maximum Telegram `initData` age; default 3600
- `TELEGRAM_INIT_DATA_FUTURE_SKEW_SECONDS`: accepted Telegram clock skew; default 30

Example public-key configuration (the JSON `\n` sequences decode to PEM newlines):

```bash
WKYC_ASSERTION_ISSUER=worldkyc-web
WKYC_ASSERTION_AUDIENCE=worldkyc-tma
WKYC_ASSERTION_PUBLIC_KEYS_JSON='{"wkyc-2026-08":"-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----"}'
WKYC_TELEGRAM_CONNECT_URL=https://app.worldkyc.com/connect-telegram
```

`Issuer`, `Audience`, and `KeyId` on WKYC_web must exactly match these TMA values. A mismatch intentionally produces `401`.

### Rollback

If acceptance checks fail, stop all services before rollback, restore the final backup, and deploy the pre-migration build. Because the first migration retains the legacy tables and columns, application rollback may also be possible without restoring data, but a database restore is the authoritative rollback method.

## Cleanup after stabilization

After a separate observation period:

- Remove `TmaBackend:LoginId`, `TmaBackend:Password`, and production static `InitData`.
- Remove the TMA WorldKYC login/password form.
- Retire `/api/tma/login` and legacy `/api/v1/auth` credential/token ingestion.
- Stop and remove TMA token refresh storage and workers.
- Remove obsolete Telegram ownership columns only after all queries use `userId`.
- Replace tokens embedded in WKYC authentication-cookie claims with an opaque server-side session.
- Encrypt any remaining server-side refresh tokens and implement rotation/revocation.
- Remove authentication response and token logging, and rotate any exposed credentials.

## Immediate security requirements

- Remove sensitive authentication-response logging in WKYC.
- Never enable configured shared WorldKYC credentials or static Telegram `initData` in production.
- Add Telegram `auth_date` freshness validation before exposing the new flow.
- Do not accept a client-supplied WorldKYC `userId` as proof of identity.
- Do not expose internal assertions or signing keys to browser code.

## Final outcome

WorldKYC is the sole WorldKYC credential/session authority. TMA is a relying service that accepts short-lived delegated identity from WKYC and Telegram identity from Telegram, resolving both to the same WorldKYC account. Non-Telegram users can use VMail through WKYC, while migrated and newly connected Telegram users continue to use the Mini App, inline VLinks, notifications, and VMail.
