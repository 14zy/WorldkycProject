import logging
import time
from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent

import data.repository.telegramLinkRepository as telegramLinkRepository
import data.repository.verifiedLinkRepository as verifiedLinkRepository
from aiogram import Router
from config.config import WKYC_VLINK_BASE_URL

logging.basicConfig(level=logging.INFO)

router = Router()
logger = logging.getLogger(__name__)
INLINE_CACHE_TTL_SECONDS = 45
_inline_links_cache = {}


def _searchable_fields(link):
    if isinstance(link, dict):
        reference = str(link.get("verifiedLinkReference") or link.get("reference") or "")
        name = str(link.get("verifiedLinkName") or link.get("name") or "")
        link_id = str(link.get("verifiedLinkId") or link.get("id") or reference)
    else:
        reference = str(link.reference or "")
        name = str(link.name or "")
        link_id = reference
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


def _store_cached_links(user_id: int, links):
    _inline_links_cache[user_id] = {
        "links": links,
        "fetched_at": time.monotonic(),
    }


@router.inline_query()
async def inline(query: InlineQuery):
    user_id = query.from_user.id
    account_link = telegramLinkRepository.find_active_by_telegram_id(user_id)
    links = _get_cached_links(user_id)
    if links is None and account_link is not None:
        links = verifiedLinkRepository.list_for_account(account_link.userId)
        _store_cached_links(user_id, links)
        logger.info(
            "Inline account cache refresh telegram_id=%s user_id=%s links=%s query=%r",
            user_id,
            account_link.userId,
            len(links),
            query.query,
        )

    if account_link is None:
        item = InlineQueryResultArticle(
            id="1",
            title="Telegram account is not linked",
            input_message_content=InputTextMessageContent(
                message_text="Open the Mini App to connect your WorldKYC account."
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
            description="Your synchronized WorldKYC VLinks are temporarily unavailable.",
        )
        await query.answer([item], cache_time=1, is_personal=True)
    else:
        answer_item = []
        matched_links = [link for link in links if _matches_query(link, query.query)]
        for link in matched_links[:50]:
            verified_link_reference, verified_link_name, verified_link_id, _url = _searchable_fields(link)
            verified_link_reference = verified_link_reference or "unknown"
            verified_link_name = verified_link_name or "Unnamed"
            verified_link_id = verified_link_id or str(len(answer_item) + 1)
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
