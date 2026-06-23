import asyncio
import logging

from api.worldKycApi import extract_verified_links, get_verified_links
import data.repository.userRepository as userRepository
import data.repository.verifiedLinkRepository as verifiedLinkRepository
from config.config import WKYC_VLINK_SYNC_INTERVAL_SECONDS
from services.sessionService import (
    AuthSessionExpiredError,
    SessionNotLinkedError,
    call_with_valid_session,
)


logger = logging.getLogger(__name__)


def _normalize_link_payload(payload) -> list[dict]:
    items = []
    for link in extract_verified_links(payload):
        reference = link.get("verifiedLinkReference") or link.get("reference")
        if not isinstance(reference, str) or not reference.strip():
            continue
        items.append(link)
    return items


def _persist_synced_links(telegram_id: int, user_id: str, payload):
    links = _normalize_link_payload(payload)
    references = verifiedLinkRepository.upsert_links(telegram_id, user_id, links)
    verifiedLinkRepository.delete_missing_links_for_user(telegram_id, references)
    return references


async def sync_user_vlinks(telegram_id: int, payload=None):
    user = userRepository.findUserByTelegramId(telegram_id)
    if not user or not user.userId or not user.accessToken or not user.refreshToken:
        raise SessionNotLinkedError()

    resolved_payload = payload
    if resolved_payload is None:
        result = await call_with_valid_session(
            telegram_id,
            lambda token: get_verified_links(token),
        )
        if not result.get("ok"):
            raise RuntimeError(result.get("message", "Failed to sync verified links"))
        resolved_payload = result.get("payload")

    references = _persist_synced_links(telegram_id, user.userId, resolved_payload)
    logger.info("Synced verified links telegramId=%s count=%s", telegram_id, len(references))
    return references


async def sync_all_linked_users_loop():
    while True:
        try:
            users = userRepository.findLinkedUsers()
            for user in users:
                if not user or not user.telegramId:
                    continue
                try:
                    await sync_user_vlinks(user.telegramId)
                except SessionNotLinkedError:
                    continue
                except AuthSessionExpiredError:
                    logger.info("Skipping VLink sync for expired session telegramId=%s", user.telegramId)
                except RuntimeError as exc:
                    logger.warning("VLink sync failed for telegramId=%s: %s", user.telegramId, exc)
        except Exception:
            logger.exception("Background verified link sync loop failed")

        await asyncio.sleep(WKYC_VLINK_SYNC_INTERVAL_SECONDS)
