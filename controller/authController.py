import asyncio
import json
from typing import Any

from aiohttp import web

import data.repository.userRepository as userRepository
from api.worldKycApi import authenticate, extract_tokens, extract_user_id
from config.config import AUTHORIZED_TOKEN
from services.sessionService import store_login_session


DEPRECATION_WARNING = '299 - "POST /api/v1/auth token-ingest mode is deprecated; use self-auth payloads with loginId/password instead."'


def _is_authorized(request) -> bool:
    auth_header = request.headers.get("Authorization")
    return bool(auth_header and auth_header == f"Bearer {AUTHORIZED_TOKEN}")


def _validate_telegram_id(value: Any):
    if not isinstance(value, int):
        return {"error": "Invalid type for telegramId", "expected": "int"}
    return None


def _validate_compatibility_payload(json_data):
    required_fields = ["telegramId", "userId", "accessToken", "refreshToken"]
    missing_fields = [field for field in required_fields if field not in json_data]
    if missing_fields:
        return {"error": "Missing fields", "missing_fields": missing_fields}

    telegram_error = _validate_telegram_id(json_data["telegramId"])
    if telegram_error:
        return telegram_error

    if not isinstance(json_data["userId"], str):
        return {"error": "Invalid type for userId", "expected": "str"}
    if not isinstance(json_data["accessToken"], str):
        return {"error": "Invalid type for accessToken", "expected": "str"}
    if not isinstance(json_data["refreshToken"], str):
        return {"error": "Invalid type for refreshToken", "expected": "str"}

    return None


def _validate_self_auth_payload(json_data):
    required_fields = ["telegramId", "loginId", "password"]
    missing_fields = [field for field in required_fields if field not in json_data]
    if missing_fields:
        return {"error": "Missing fields", "missing_fields": missing_fields}

    telegram_error = _validate_telegram_id(json_data["telegramId"])
    if telegram_error:
        return telegram_error

    if not isinstance(json_data["loginId"], str):
        return {"error": "Invalid type for loginId", "expected": "str"}
    if not isinstance(json_data["password"], str):
        return {"error": "Invalid type for password", "expected": "str"}

    caller_id = json_data.get("callerId")
    if caller_id is not None and not isinstance(caller_id, str):
        return {"error": "Invalid type for callerId", "expected": "str"}

    for field in ("includeUserSettingsInResponse", "includeAccessRightsWithUserSettings"):
        if field in json_data and not isinstance(json_data[field], bool):
            return {"error": f"Invalid type for {field}", "expected": "bool"}

    return None


def _build_error_response(result):
    details = result.get("details")
    if isinstance(details, dict) and details:
        payload = {"error": result.get("message", "Upstream API error"), "details": details}
    elif details:
        payload = {"error": result.get("message", "Upstream API error"), "details": str(details)}
    else:
        payload = {"error": result.get("message", "Upstream API error")}

    return web.json_response(payload, status=result.get("status_code", 502))


async def _handle_self_auth(data):
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: authenticate(
            data["loginId"],
            data["password"],
            caller_id=data.get("callerId"),
            include_user_settings_in_response=data.get("includeUserSettingsInResponse", True),
            include_access_rights_with_user_settings=data.get("includeAccessRightsWithUserSettings", False),
        ),
    )

    if not result.get("ok"):
        return _build_error_response(result)

    payload = result.get("payload") or {}
    access_token, refresh_token = extract_tokens(payload)
    if not access_token or not refresh_token:
        return web.json_response(
            {
                "error": "WorldKyc Authenticate response did not include expected tokens",
                "details": payload,
            },
            status=502,
        )

    upstream_user_id = extract_user_id(payload, fallback=data["loginId"])
    store_login_session(data["telegramId"], upstream_user_id, payload)
    return web.json_response(payload, status=result.get("status_code", 200))


async def handle_request(request):
    if not _is_authorized(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        data = await request.json()
    except json.JSONDecodeError as exc:
        return web.json_response({"error": "Bad Request", "message": str(exc)}, status=400)

    is_compatibility_flow = "accessToken" in data or "refreshToken" in data or "userId" in data
    is_self_auth_flow = "loginId" in data or "password" in data

    if is_compatibility_flow and is_self_auth_flow:
        return web.json_response(
            {"error": "Request must contain either compatibility token fields or self-auth credentials, not both."},
            status=400,
        )

    if is_self_auth_flow:
        validation_error = _validate_self_auth_payload(data)
        if validation_error:
            return web.json_response(validation_error, status=400)
        return await _handle_self_auth(data)

    validation_error = _validate_compatibility_payload(data)
    if validation_error:
        return web.json_response(validation_error, status=400)

    userRepository.saveUser(data["telegramId"], data["userId"], data["accessToken"], data["refreshToken"])
    return web.Response(status=204, headers={"Warning": DEPRECATION_WARNING})
