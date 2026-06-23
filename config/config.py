import os

from aiogram import Bot
from dotenv import load_dotenv


def _get_int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default

    try:
        return int(value)
    except ValueError:
        return default


def _get_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
AUTHORIZED_TOKEN = os.getenv("AUTHORIZED_TOKEN")
WKYC_BASE_URL = os.getenv("WKYC_BASE_URL", "https://www.bizcurrency.com:20500").rstrip("/")
WKYC_VLINK_BASE_URL = os.getenv("WKYC_VLINK_BASE_URL", "https://app.worldkyc.com/vl/").rstrip("/") + "/"
WKYC_CALLER_ID = os.getenv("WKYC_CALLER_ID")
WKYC_TIMEOUT_SECONDS = _get_int_env("WKYC_TIMEOUT_SECONDS", 15)
WKYC_REFRESH_WINDOW_SECONDS = _get_int_env("WKYC_REFRESH_WINDOW_SECONDS", 300)
WKYC_REFRESH_SCAN_INTERVAL_SECONDS = _get_int_env("WKYC_REFRESH_SCAN_INTERVAL_SECONDS", 60)
WKYC_REFRESH_TOKEN_DEFAULT_TTL_HOURS = _get_int_env("WKYC_REFRESH_TOKEN_DEFAULT_TTL_HOURS", 24)
WKYC_VLINK_SYNC_INTERVAL_SECONDS = _get_int_env("WKYC_VLINK_SYNC_INTERVAL_SECONDS", 900)
TMA_URL = os.getenv("TMA_URL", "https://tonstealthid.com/tma")
IMAP_HOST = os.getenv("IMAP_HOST")
IMAP_PORT = _get_int_env("IMAP_PORT", 993)
IMAP_USERNAME = os.getenv("IMAP_USERNAME")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD")
IMAP_MAILBOX = os.getenv("IMAP_MAILBOX", "INBOX")
IMAP_USE_SSL = _get_bool_env("IMAP_USE_SSL", True)
IMAP_POLL_INTERVAL_SECONDS = _get_int_env("IMAP_POLL_INTERVAL_SECONDS", 60)

url_webapp = "https://t.me/tonstealthid_bot"
bot = Bot(token=BOT_TOKEN)
