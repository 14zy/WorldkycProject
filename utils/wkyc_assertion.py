from __future__ import annotations

from dataclasses import dataclass

import jwt

from config.config import (
    WKYC_ASSERTION_AUDIENCE,
    WKYC_ASSERTION_CLOCK_SKEW_SECONDS,
    WKYC_ASSERTION_ISSUER,
    WKYC_ASSERTION_KEY_ID,
    WKYC_ASSERTION_MAX_LIFETIME_SECONDS,
    WKYC_ASSERTION_PUBLIC_KEY,
    WKYC_ASSERTION_PUBLIC_KEYS,
)


class WkycAssertionError(ValueError):
    pass


@dataclass(frozen=True)
class WkycAssertion:
    user_id: str
    scopes: frozenset[str]
    jti: str
    claims: dict

    def require_scope(self, required_scope: str) -> None:
        if required_scope not in self.scopes:
            raise WkycAssertionError(f"Assertion does not grant {required_scope}")


def _configured_keys() -> dict[str, str]:
    keys = {
        str(key_id): value
        for key_id, value in WKYC_ASSERTION_PUBLIC_KEYS.items()
        if isinstance(key_id, str) and isinstance(value, str) and value.strip()
    }
    if WKYC_ASSERTION_PUBLIC_KEY:
        keys.setdefault(WKYC_ASSERTION_KEY_ID, WKYC_ASSERTION_PUBLIC_KEY)
    return keys


def _parse_scopes(raw_scope) -> frozenset[str]:
    if isinstance(raw_scope, str):
        return frozenset(part for part in raw_scope.split() if part)
    if isinstance(raw_scope, list) and all(isinstance(item, str) for item in raw_scope):
        return frozenset(item for item in raw_scope if item)
    raise WkycAssertionError("Assertion scope is missing or invalid")


def validate_wkyc_assertion(token: str, required_scope: str | None = None) -> WkycAssertion:
    keys = _configured_keys()
    if not keys:
        raise WkycAssertionError("WKYC assertion public key is not configured")

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise WkycAssertionError("Assertion header is invalid") from exc

    if header.get("alg") != "RS256":
        raise WkycAssertionError("Assertion algorithm is not allowed")
    key_id = header.get("kid")
    if not isinstance(key_id, str) or key_id not in keys:
        raise WkycAssertionError("Assertion signing key is unknown")

    try:
        claims = jwt.decode(
            token,
            keys[key_id],
            algorithms=["RS256"],
            audience=WKYC_ASSERTION_AUDIENCE,
            issuer=WKYC_ASSERTION_ISSUER,
            leeway=WKYC_ASSERTION_CLOCK_SKEW_SECONDS,
            options={"require": ["iss", "sub", "aud", "iat", "nbf", "exp", "jti", "scope"]},
        )
    except jwt.PyJWTError as exc:
        raise WkycAssertionError("Assertion validation failed") from exc

    user_id = claims.get("sub")
    jti = claims.get("jti")
    issued_at = claims.get("iat")
    expires_at = claims.get("exp")
    if not isinstance(user_id, str) or not user_id.strip():
        raise WkycAssertionError("Assertion subject is invalid")
    if not isinstance(jti, str) or not jti.strip():
        raise WkycAssertionError("Assertion jti is invalid")
    if not isinstance(issued_at, (int, float)) or not isinstance(expires_at, (int, float)):
        raise WkycAssertionError("Assertion lifetime is invalid")
    if expires_at <= issued_at or expires_at - issued_at > WKYC_ASSERTION_MAX_LIFETIME_SECONDS:
        raise WkycAssertionError("Assertion lifetime exceeds the allowed maximum")

    assertion = WkycAssertion(
        user_id=user_id.strip(),
        scopes=_parse_scopes(claims.get("scope")),
        jti=jti,
        claims=claims,
    )
    if required_scope:
        assertion.require_scope(required_scope)
    return assertion
