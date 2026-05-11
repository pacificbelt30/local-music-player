"""Discord Webhook notification service.

Reads webhook URL and per-event enable flags from DB (AppSetting).
Falls back to DISCORD_WEBHOOK_URL env var when DB is unreachable (e.g. during DB errors).
"""
import httpx

from app.config import settings as _env
from app.database import SessionLocal
from app.models import AppSetting

# Notification event types and their defaults
EVENTS: dict[str, bool] = {
    "notify_on_download_complete": False,
    "notify_on_download_failed": True,
    "notify_on_db_error": True,
    "notify_on_youtube_auth_expired": True,
    "notify_on_oauth_expiry_warning": True,
}


def _get_config() -> tuple[str | None, dict[str, bool]]:
    """Return (webhook_url, {event: enabled}).  Falls back to env when DB is down."""
    try:
        db = SessionLocal()
        try:
            url_row = db.get(AppSetting, "discord_webhook_url")
            webhook_url = (url_row.value if url_row and url_row.value else None) or _env.discord_webhook_url or None
            enabled: dict[str, bool] = {}
            for key, default in EVENTS.items():
                row = db.get(AppSetting, key)
                enabled[key] = (row.value.lower() in ("true", "1")) if row else default
        finally:
            db.close()
        return webhook_url, enabled
    except Exception:
        return _env.discord_webhook_url or None, dict(EVENTS)


def _send(webhook_url: str, title: str, description: str, color: int) -> None:
    try:
        with httpx.Client(timeout=10) as client:
            client.post(webhook_url, json={"embeds": [{"title": title, "description": description, "color": color}]})
    except Exception:
        pass


def notify(event_type: str, title: str, description: str, color: int) -> None:
    """Send a Discord notification if the event type is enabled and a webhook URL is set."""
    webhook_url, enabled = _get_config()
    if not webhook_url or not enabled.get(event_type, False):
        return
    _send(webhook_url, title, description, color)
