import uuid

import requests

from config.config import WKYC_BASE_URL, WKYC_CALLER_ID, WKYC_TIMEOUT_SECONDS


def _response_payload(response: requests.Response):
    content_type = response.headers.get("Content-Type", "")
    if "application/json" in content_type.lower():
        try:
            return response.json()
        except ValueError:
            return {"raw": response.text}

    if response.text:
        return {"raw": response.text}

    return None


def _extract_problem_message(payload) -> str:
    if not isinstance(payload, dict):
        return "WorldKyc API returned an error"

    problems = payload.get("problems")
    if isinstance(problems, list) and problems:
        first_problem = problems[0]
        if isinstance(first_problem, dict):
            message = first_problem.get("message") or first_problem.get("messageDetails")
            if message:
                return message

    return payload.get("message") or "WorldKyc API returned an error"


def _request(method: str, path: str, *, access_token=None, params=None, json_body=None):
    headers = {"Accept": "application/json"}
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    try:
        response = requests.request(
            method,
            f"{WKYC_BASE_URL}{path}",
            headers=headers,
            params=params,
            json=json_body,
            timeout=WKYC_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        return {
            "ok": False,
            "status_code": 502,
            "message": "Failed to reach WorldKyc API",
            "details": str(exc),
        }

    payload = _response_payload(response)
    if response.ok:
        return {
            "ok": True,
            "status_code": response.status_code,
            "payload": payload,
        }

    return {
        "ok": False,
        "status_code": response.status_code,
        "message": _extract_problem_message(payload),
        "details": payload,
    }


def _validate_caller_id(caller_id: str):
    if not caller_id:
        return {
            "ok": False,
            "status_code": 400,
            "message": "WKYC callerId is required",
            "details": {
                "error": "Set WKYC_CALLER_ID in the environment or provide callerId in the request body."
            },
        }

    try:
        uuid.UUID(caller_id)
    except ValueError:
        return {
            "ok": False,
            "status_code": 400,
            "message": "WKYC callerId must be a UUID",
            "details": {"error": "callerId must be a valid UUID string."},
        }

    return None


def authenticate(
    login_id: str,
    password: str,
    *,
    caller_id=None,
    include_user_settings_in_response=True,
    include_access_rights_with_user_settings=False,
):
    resolved_caller_id = caller_id or WKYC_CALLER_ID
    caller_id_error = _validate_caller_id(resolved_caller_id)
    if caller_id_error:
        return caller_id_error

    request_body = {
        "loginId": login_id,
        "password": password,
        "callerId": resolved_caller_id,
        "includeUserSettingsInResponse": include_user_settings_in_response,
        "includeAccessRightsWithUserSettings": include_access_rights_with_user_settings,
    }
    return _request("POST", "/api/v1/Authenticate", json_body=request_body)


def refresh_authenticate(access_token: str, refresh_token: str):
    return _request(
        "POST",
        "/api/v1/Authenticate/Refresh",
        json_body={
            "accessToken": access_token,
            "refreshToken": refresh_token,
        },
    )


def search_customer_users(
    token,
    page_index=0,
    page_size=25,
    username=None,
    firstname=None,
    lastname=None,
    customer_name=None,
    wkyc_id=None,
    sort_by=None,
    sort_direction=None,
):
    params = {
        "PageIndex": page_index,
        "PageSize": page_size,
    }

    if username:
        params["UserName"] = username
    if firstname:
        params["FirstName"] = firstname
    if lastname:
        params["LastName"] = lastname
    if customer_name:
        params["CustomerName"] = customer_name
    if wkyc_id:
        params["WKYCId"] = wkyc_id
    if sort_by:
        params["SortBy"] = sort_by
    if sort_direction:
        params["SortDirection"] = sort_direction

    return _request(
        "GET",
        "/api/v1/CustomerUser/Search",
        access_token=token,
        params=params,
    )


def get_verified_links(token, page_index=0, page_size=10000):
    params = {
        "PageIndex": page_index,
        "PageSize": page_size,
    }
    return _request(
        "GET",
        "/api/v1/VerifiedLink/Search",
        access_token=token,
        params=params,
    )


def extract_verified_links(payload):
    if isinstance(payload, list):
        return payload

    if not isinstance(payload, dict):
        return []

    records = payload.get("records")
    if isinstance(records, dict):
        verified_links = records.get("verifiedLinks")
        if isinstance(verified_links, list):
            return verified_links

    verified_links = payload.get("verifiedLinks")
    if isinstance(verified_links, list):
        return verified_links

    items = payload.get("items")
    if isinstance(items, list):
        return items

    return []


def extract_tokens(payload):
    token_container = payload.get("tokens") if isinstance(payload, dict) else None
    if not isinstance(token_container, dict):
        token_container = payload if isinstance(payload, dict) else {}

    access_token = token_container.get("accessToken") or token_container.get("token")
    refresh_token = token_container.get("refreshToken")
    return access_token, refresh_token


def extract_token_lifetime_fields(payload):
    token_container = payload.get("tokens") if isinstance(payload, dict) else None
    if not isinstance(token_container, dict):
        token_container = payload if isinstance(payload, dict) else {}

    fallback_payload = payload if isinstance(payload, dict) else {}
    access_expires_minutes = token_container.get("accessTokenExpiresInMinutes")
    if access_expires_minutes is None:
        access_expires_minutes = fallback_payload.get("accessTokenExpiresInMinutes")

    refresh_expires_hours = token_container.get("refreshTokenExpiresInHours")
    if refresh_expires_hours is None:
        refresh_expires_hours = fallback_payload.get("refreshTokenExpiresInHours")
    return access_expires_minutes, refresh_expires_hours


def extract_user_id(payload, fallback=None):
    if not isinstance(payload, dict):
        return fallback

    candidate_paths = (
        ("userId",),
        ("memberId",),
        ("tokens", "userId"),
        ("tokens", "memberId"),
        ("userSettings", "userId"),
        ("userSettings", "memberId"),
        ("userSettings", "user", "userId"),
        ("userSettings", "currentUser", "userId"),
    )

    for path in candidate_paths:
        current = payload
        for key in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(key)

        if isinstance(current, str) and current:
            return current

    return fallback


def extract_user_email(payload):
    if not isinstance(payload, dict):
        return None

    candidate_paths = (
        ("userSettings", "emailAddress"),
        ("userSettings", "user", "emailAddress"),
        ("userSettings", "currentUser", "emailAddress"),
    )

    for path in candidate_paths:
        current = payload
        for key in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(key)
        if isinstance(current, str):
            normalized = current.strip()
            if normalized:
                return normalized

    return None
