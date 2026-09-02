import os
import json

try:
    from aiogram import Bot
except ImportError:  # pragma: no cover - test environments may not have runtime deps installed
    Bot = None

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - test environments may not have runtime deps installed
    def load_dotenv():
        return False


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


def _get_json_env(name: str, default):
    value = os.getenv(name)
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_INIT_DATA_MAX_AGE_SECONDS = _get_int_env("TELEGRAM_INIT_DATA_MAX_AGE_SECONDS", 3600)
TELEGRAM_INIT_DATA_FUTURE_SKEW_SECONDS = _get_int_env("TELEGRAM_INIT_DATA_FUTURE_SKEW_SECONDS", 30)
WKYC_ASSERTION_ISSUER = os.getenv("WKYC_ASSERTION_ISSUER", "worldkyc-web")
WKYC_ASSERTION_AUDIENCE = os.getenv("WKYC_ASSERTION_AUDIENCE", "worldkyc-tma")
WKYC_ASSERTION_PUBLIC_KEY = os.getenv("WKYC_ASSERTION_PUBLIC_KEY")
WKYC_ASSERTION_KEY_ID = os.getenv("WKYC_ASSERTION_KEY_ID", "default")
WKYC_ASSERTION_PUBLIC_KEYS = _get_json_env("WKYC_ASSERTION_PUBLIC_KEYS_JSON", {})
WKYC_ASSERTION_MAX_LIFETIME_SECONDS = _get_int_env("WKYC_ASSERTION_MAX_LIFETIME_SECONDS", 300)
WKYC_ASSERTION_CLOCK_SKEW_SECONDS = _get_int_env("WKYC_ASSERTION_CLOCK_SKEW_SECONDS", 30)
WKYC_TELEGRAM_CONNECT_URL = os.getenv(
    "WKYC_TELEGRAM_CONNECT_URL",
    "https://app.worldkyc.com/connect-telegram",
)
TELEGRAM_CONNECT_CODE_TTL_SECONDS = _get_int_env("TELEGRAM_CONNECT_CODE_TTL_SECONDS", 300)
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
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_BASE_URL = os.getenv("RESEND_BASE_URL", "https://api.resend.com").rstrip("/")
RESEND_TIMEOUT_SECONDS = _get_int_env("RESEND_TIMEOUT_SECONDS", 15)
RESEND_WEBHOOK_SECRET = os.getenv("RESEND_WEBHOOK_SECRET")
MAIL_FROM_DOMAIN = os.getenv("MAIL_FROM_DOMAIN", "tonstealthid.com").strip()
VMAIL_ACCOUNT_SEND_LIMIT_PER_HOUR = _get_int_env("VMAIL_ACCOUNT_SEND_LIMIT_PER_HOUR", 30)
VMAIL_LINK_SEND_LIMIT_PER_HOUR = _get_int_env("VMAIL_LINK_SEND_LIMIT_PER_HOUR", 10)

url_webapp = "https://t.me/tonstealthid_bot"
bot = Bot(token=BOT_TOKEN) if Bot and BOT_TOKEN else None
