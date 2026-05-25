from aiohttp import web
import logging
from config.config import AUTHORIZED_TOKEN
from api.worldKycApi import search_customer_users
import data.repository.userRepository as userRepository
from services.sessionService import (
    AUTH_SESSION_EXPIRED_CODE,
    AuthSessionExpiredError,
    SessionNotLinkedError,
    call_with_valid_session,
)


logger = logging.getLogger(__name__)


def _is_authorized(request) -> bool:
    auth_header = request.headers.get("Authorization")
    return bool(auth_header and auth_header == f"Bearer {AUTHORIZED_TOKEN}")


def _build_error_response(result):
    details = result.get("details")
    if isinstance(details, dict) and details:
        payload = {"error": result.get("message", "Upstream API error"), "details": details}
    elif details:
        payload = {"error": result.get("message", "Upstream API error"), "details": str(details)}
    else:
        payload = {"error": result.get("message", "Upstream API error")}

    return web.json_response(payload, status=result.get("status_code", 502))


def _session_expired_response():
    return web.json_response(
        {"error": "Session expired", "code": AUTH_SESSION_EXPIRED_CODE},
        status=401,
    )


async def handle_customer_search(request):
    if not _is_authorized(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    telegram_id_raw = request.query.get("telegramId")
    if telegram_id_raw is None:
        return web.json_response({"error": "telegramId is required"}, status=400)

    try:
        telegram_id = int(telegram_id_raw)
        page_index = int(request.query.get("PageIndex", 0))
        page_size = int(request.query.get("PageSize", 25))
    except ValueError:
        return web.json_response({"error": "Invalid query parameter values"}, status=400)

    if page_index < 0 or page_size <= 0:
        return web.json_response({"error": "PageIndex must be >= 0 and PageSize must be > 0"}, status=400)

    username = request.query.get("UserName")
    firstname = request.query.get("FirstName")
    lastname = request.query.get("LastName")
    customer_name = request.query.get("CustomerName")
    wkyc_id = request.query.get("WKYCId")
    sort_by = request.query.get("SortBy")
    sort_direction = request.query.get("SortDirection")

    try:
        user = userRepository.findUserByTelegramId(telegram_id)
        if user is None:
            return web.json_response({"error": "User not found"}, status=404)
        if not user.accessToken or not user.refreshToken:
            return web.json_response({"error": "User access token not found"}, status=400)

        result = await call_with_valid_session(telegram_id, lambda token: search_customer_users(
            token,
            page_index=page_index,
            page_size=page_size,
            username=username,
            firstname=firstname,
            lastname=lastname,
            customer_name=customer_name,
            wkyc_id=wkyc_id,
            sort_by=sort_by,
            sort_direction=sort_direction
        ))
    except AuthSessionExpiredError:
        return _session_expired_response()
    except SessionNotLinkedError:
        return web.json_response({"error": "User is not linked"}, status=404)

    except Exception:
        logger.exception("Customer search handler failed for telegramId=%s", telegram_id_raw)
        return web.json_response({"error": "Internal error"}, status=500)

    if not result.get("ok"):
        logger.error(
            "Customer search upstream failure for telegramId=%s: status=%s details=%s",
            telegram_id,
            result.get("status_code"),
            result.get("details"),
        )
        return _build_error_response(result)

    return web.json_response(result.get("payload"), status=result.get("status_code", 200))
