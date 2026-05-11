"""Tests for the Discord notification service."""
from unittest.mock import MagicMock, patch

import pytest

from app.models import AppSetting
from app.services.notification import EVENTS, notify, _get_config


# ── _get_config ────────────────────────────────────────────────────────────────

class TestGetConfig:
    def test_returns_empty_url_when_no_db_row_and_no_env(self, db):
        with patch("app.services.notification._env") as mock_env:
            mock_env.discord_webhook_url = ""
            with patch("app.services.notification.SessionLocal", return_value=db):
                url, enabled = _get_config()
        assert url is None

    def test_returns_url_from_db(self, db):
        db.add(AppSetting(key="discord_webhook_url", value="https://discord.com/api/webhooks/1/abc"))
        db.commit()
        with patch("app.services.notification._env") as mock_env:
            mock_env.discord_webhook_url = ""
            with patch("app.services.notification.SessionLocal", return_value=db):
                url, _ = _get_config()
        assert url == "https://discord.com/api/webhooks/1/abc"

    def test_falls_back_to_env_when_db_url_empty(self, db):
        db.add(AppSetting(key="discord_webhook_url", value=""))
        db.commit()
        with patch("app.services.notification._env") as mock_env:
            mock_env.discord_webhook_url = "https://env-webhook.example.com"
            with patch("app.services.notification.SessionLocal", return_value=db):
                url, _ = _get_config()
        assert url == "https://env-webhook.example.com"

    def test_falls_back_to_env_when_db_unreachable(self):
        with patch("app.services.notification._env") as mock_env:
            mock_env.discord_webhook_url = "https://fallback.example.com"
            with patch("app.services.notification.SessionLocal", side_effect=Exception("DB down")):
                url, enabled = _get_config()
        assert url == "https://fallback.example.com"
        assert enabled == EVENTS  # falls back to module-level defaults

    def test_returns_default_enabled_flags_when_no_db_rows(self, db):
        with patch("app.services.notification._env") as mock_env:
            mock_env.discord_webhook_url = ""
            with patch("app.services.notification.SessionLocal", return_value=db):
                _, enabled = _get_config()
        assert enabled["notify_on_download_complete"] is False
        assert enabled["notify_on_download_failed"] is True
        assert enabled["notify_on_db_error"] is True
        assert enabled["notify_on_youtube_auth_expired"] is True

    def test_reads_enabled_flags_from_db(self, db):
        db.add(AppSetting(key="notify_on_download_complete", value="true"))
        db.add(AppSetting(key="notify_on_download_failed", value="false"))
        db.commit()
        with patch("app.services.notification._env") as mock_env:
            mock_env.discord_webhook_url = ""
            with patch("app.services.notification.SessionLocal", return_value=db):
                _, enabled = _get_config()
        assert enabled["notify_on_download_complete"] is True
        assert enabled["notify_on_download_failed"] is False


# ── notify ────────────────────────────────────────────────────────────────────

class TestNotify:
    def _make_config(self, webhook_url: str | None, event_enabled: bool):
        enabled = {k: False for k in EVENTS}
        enabled["notify_on_download_failed"] = event_enabled
        return webhook_url, enabled

    def test_sends_when_enabled_and_url_set(self, db):
        config = self._make_config("https://discord.com/api/webhooks/1/x", True)
        with patch("app.services.notification._get_config", return_value=config):
            with patch("app.services.notification._send") as mock_send:
                notify("notify_on_download_failed", "失敗", "詳細", 0xFF0000)
        mock_send.assert_called_once_with("https://discord.com/api/webhooks/1/x", "失敗", "詳細", 0xFF0000)

    def test_does_not_send_when_event_disabled(self, db):
        config = self._make_config("https://discord.com/api/webhooks/1/x", False)
        with patch("app.services.notification._get_config", return_value=config):
            with patch("app.services.notification._send") as mock_send:
                notify("notify_on_download_failed", "失敗", "詳細", 0xFF0000)
        mock_send.assert_not_called()

    def test_does_not_send_when_no_webhook_url(self, db):
        config = self._make_config(None, True)
        with patch("app.services.notification._get_config", return_value=config):
            with patch("app.services.notification._send") as mock_send:
                notify("notify_on_download_failed", "失敗", "詳細", 0xFF0000)
        mock_send.assert_not_called()

    def test_unknown_event_type_does_not_send(self, db):
        config = ("https://discord.com/api/webhooks/1/x", {})
        with patch("app.services.notification._get_config", return_value=config):
            with patch("app.services.notification._send") as mock_send:
                notify("notify_on_unknown_event", "test", "test", 0x0)
        mock_send.assert_not_called()

    def test_db_error_notification_uses_env_fallback(self):
        """When DB is unavailable, DB error notifications still fire via env fallback."""
        with patch("app.services.notification.SessionLocal", side_effect=Exception("DB down")):
            with patch("app.services.notification._env") as mock_env:
                mock_env.discord_webhook_url = "https://fallback.example.com"
                with patch("app.services.notification._send") as mock_send:
                    notify("notify_on_db_error", "DB障害", "テスト", 0xFEE75C)
        mock_send.assert_called_once()
        assert mock_send.call_args[0][0] == "https://fallback.example.com"
