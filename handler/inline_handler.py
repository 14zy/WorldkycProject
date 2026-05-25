import logging
import time
from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent

import data.repository.userRepository as userRepository
from aiogram import Router
from api.worldKycApi import extract_verified_links, get_verified_links
from config.config import WKYC_VLINK_BASE_URL
from services.sessionService import AuthSessionExpiredError, SessionNotLinkedError, call_with_valid_session

logging.basicConfig(level=logging.INFO)

router = Router()
logger = logging.getLogger(__name__)
INLINE_CACHE_TTL_SECONDS = 45
_inline_links_cache = {}


def _searchable_fields(link):
    reference = str(link.get("verifiedLinkReference") or link.get("reference") or "")
    name = str(link.get("verifiedLinkName") or link.get("name") or "")
    link_id = str(link.get("verifiedLinkId") or link.get("id") or "")
    url = f"{WKYC_VLINK_BASE_URL}{reference}" if reference else ""
    return reference, name, link_id, url


def _matches_query(link, raw_query: str):
    query = raw_query.strip().lower()
    if not query:
        return True

    reference, name, link_id, url = _searchable_fields(link)
    haystack = " ".join((reference, name, link_id, url)).lower()
    return query in haystack


def _get_cached_links(user_id: int):
    entry = _inline_links_cache.get(user_id)
    if not entry:
        return None

    age = time.monotonic() - entry["fetched_at"]
    if age > INLINE_CACHE_TTL_SECONDS:
        return None

    return entry["links"]


def _get_stale_links(user_id: int):
    entry = _inline_links_cache.get(user_id)
    if not entry:
        return None
    return entry["links"]


def _store_cached_links(user_id: int, links):
    _inline_links_cache[user_id] = {
        "links": links,
        "fetched_at": time.monotonic(),
    }


@router.inline_query()
async def inline(query: InlineQuery):
    user_id = query.from_user.id
    user = userRepository.findUserByTelegramId(user_id)
    links = _get_cached_links(user_id)
    session_expired = False
    if links is None and user and user.accessToken and user.refreshToken:
        try:
            result = await call_with_valid_session(user_id, lambda token: get_verified_links(token))
        except AuthSessionExpiredError:
            session_expired = True
            links = None
        except SessionNotLinkedError:
            links = None
        else:
            if result.get("ok"):
                links = extract_verified_links(result.get("payload"))
                _store_cached_links(user_id, links)
                logger.info(
                    "Inline cache refresh telegram_id=%s links=%s query=%r",
                    user_id,
                    len(links),
                    query.query,
                )
            else:
                links = _get_stale_links(user_id)
                logger.warning(
                    "Inline upstream failure telegram_id=%s status=%s query=%r details=%s stale_cache=%s",
                    user_id,
                    result.get("status_code"),
                    query.query,
                    result.get("details"),
                    bool(links),
                )

    if session_expired:
        item = InlineQueryResultArticle(
            id="session-expired",
            title="Session expired",
            input_message_content=InputTextMessageContent(
                message_text="WorldKyc session expired. Open the Mini App and sign in again."
            ),
            description="Open the Mini App and relink your WorldKyc account.",
        )
        await query.answer([item], cache_time=1, is_personal=True)
    elif not user or not user.accessToken:
        item = InlineQueryResultArticle(
            id="1",
            title="You are not logged in",
            input_message_content=InputTextMessageContent(
                message_text="You are not logged in"
            ),
        )
        await query.answer([item], cache_time=1, is_personal=True)
    elif links is None:
        item = InlineQueryResultArticle(
            id="service-unavailable",
            title="Vlinks temporarily unavailable",
            input_message_content=InputTextMessageContent(
                message_text="Vlinks are temporarily unavailable. Please try again in a moment."
            ),
            description="The upstream WorldKyc API did not respond in time.",
        )
        await query.answer([item], cache_time=1, is_personal=True)
    else:
        answer_item = []
        matched_links = [link for link in links if _matches_query(link, query.query)]
        for link in matched_links[:50]:
            verified_link_id = str(link.get("verifiedLinkId") or link.get("id") or len(answer_item) + 1)
            verified_link_reference = link.get("verifiedLinkReference") or link.get("reference") or "unknown"
            verified_link_name = link.get("verifiedLinkName") or link.get("name") or "Unnamed"
            item = InlineQueryResultArticle(
                id=verified_link_id,
                title=f"{verified_link_reference} ({verified_link_name})",
                input_message_content=InputTextMessageContent(
                    message_text=f"{WKYC_VLINK_BASE_URL}{verified_link_reference}"
                ),
            )
            answer_item.append(item)

        if not answer_item:
            answer_item.append(
                InlineQueryResultArticle(
                    id="no-matches",
                    title="No matching vlinks",
                    input_message_content=InputTextMessageContent(
                        message_text="No matching vlinks were found."
                    ),
                    description="Try searching by alias, name, or id fragment.",
                )
            )

        logger.info(
            "Inline answer telegram_id=%s query=%r matched=%s total_cached=%s",
            user_id,
            query.query,
            len(matched_links),
            len(links),
        )
        await query.answer(answer_item, cache_time=1, is_personal=True)
