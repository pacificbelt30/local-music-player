"""Tests for sync interval settings API and scheduler interval logic."""
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from app.models import AppSetting


# ── GET /settings ─────────────────────────────────────────────────────────────

def test_get_settings_returns_defaults(client):
    resp = client.get("/api/v1/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["url_sync_interval_minutes"] == 60
    assert data["youtube_sync_interval_minutes"] == 60
    assert data["download_gain_percent"] == 0.0
    assert data["silence_trim_start_secs"] == 2.5
    assert data["silence_trim_end_secs"] == 2.5
    assert data["ffmpeg_threads"] == 1
    assert data["ffmpeg_memory_limit_mb"] == 0


def test_get_settings_reflects_db_values(client, db):
    db.add(AppSetting(key="url_sync_interval_minutes", value="30"))
    db.add(AppSetting(key="youtube_sync_interval_minutes", value="180"))
    db.add(AppSetting(key="download_gain_percent", value="25"))
    db.add(AppSetting(key="ffmpeg_threads", value="2"))
    db.add(AppSetting(key="ffmpeg_memory_limit_mb", value="512"))
    db.commit()

    data = client.get("/api/v1/settings").json()
    assert data["url_sync_interval_minutes"] == 30
    assert data["youtube_sync_interval_minutes"] == 180
    assert data["download_gain_percent"] == 25.0
    assert data["ffmpeg_threads"] == 2
    assert data["ffmpeg_memory_limit_mb"] == 512


# ── PATCH /settings ───────────────────────────────────────────────────────────

def test_update_url_interval(client):
    resp = client.patch("/api/v1/settings", json={"url_sync_interval_minutes": 30})
    assert resp.status_code == 200
    assert resp.json()["url_sync_interval_minutes"] == 30


def test_update_youtube_interval(client):
    resp = client.patch("/api/v1/settings", json={"youtube_sync_interval_minutes": 360})
    assert resp.status_code == 200
    assert resp.json()["youtube_sync_interval_minutes"] == 360


def test_update_both_intervals(client):
    resp = client.patch("/api/v1/settings", json={
        "url_sync_interval_minutes": 15,
        "youtube_sync_interval_minutes": 720,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["url_sync_interval_minutes"] == 15
    assert data["youtube_sync_interval_minutes"] == 720


def test_update_persists(client):
    client.patch("/api/v1/settings", json={"url_sync_interval_minutes": 1440})
    data = client.get("/api/v1/settings").json()
    assert data["url_sync_interval_minutes"] == 1440


def test_update_overwrites_existing(client, db):
    db.add(AppSetting(key="url_sync_interval_minutes", value="60"))
    db.commit()

    client.patch("/api/v1/settings", json={"url_sync_interval_minutes": 15})
    assert client.get("/api/v1/settings").json()["url_sync_interval_minutes"] == 15


def test_partial_update_leaves_other_unchanged(client):
    client.patch("/api/v1/settings", json={"youtube_sync_interval_minutes": 30})
    data = client.get("/api/v1/settings").json()
    assert data["url_sync_interval_minutes"] == 60    # default unchanged
    assert data["youtube_sync_interval_minutes"] == 30


def test_invalid_interval_rejected(client):
    resp = client.patch("/api/v1/settings", json={"url_sync_interval_minutes": 45})
    assert resp.status_code == 422


def test_zero_disables_auto_sync(client):
    resp = client.patch("/api/v1/settings", json={"url_sync_interval_minutes": 0})
    assert resp.status_code == 200
    assert resp.json()["url_sync_interval_minutes"] == 0


# ── Scheduler interval logic (_is_due) ────────────────────────────────────────

class TestIsDue:
    def test_due_when_no_last_run(self, db):
        from app.tasks.scheduler import _is_due
        assert _is_due(db, "url_sync_last_run", 60) is True

    def test_not_due_when_interval_is_zero(self, db):
        from app.tasks.scheduler import _is_due
        assert _is_due(db, "url_sync_last_run", 0) is False

    def test_due_when_interval_elapsed(self, db):
        from app.tasks.scheduler import _is_due
        past = datetime.now(timezone.utc) - timedelta(minutes=70)
        db.add(AppSetting(key="url_sync_last_run", value=past.isoformat()))
        db.commit()
        assert _is_due(db, "url_sync_last_run", 60) is True

    def test_not_due_when_interval_not_elapsed(self, db):
        from app.tasks.scheduler import _is_due
        recent = datetime.now(timezone.utc) - timedelta(minutes=30)
        db.add(AppSetting(key="url_sync_last_run", value=recent.isoformat()))
        db.commit()
        assert _is_due(db, "url_sync_last_run", 60) is False

    def test_due_exactly_at_boundary(self, db):
        from app.tasks.scheduler import _is_due
        exactly = datetime.now(timezone.utc) - timedelta(minutes=60, seconds=1)
        db.add(AppSetting(key="url_sync_last_run", value=exactly.isoformat()))
        db.commit()
        assert _is_due(db, "url_sync_last_run", 60) is True


# ── periodic_playlist_refresh ─────────────────────────────────────────────────

class TestPeriodicPlaylistRefresh:
    def test_skips_when_interval_zero(self, db):
        from app.tasks.scheduler import periodic_playlist_refresh
        db.add(AppSetting(key="url_sync_interval_minutes", value="0"))
        db.commit()

        with patch("app.tasks.scheduler.SessionLocal", return_value=db):
            with patch("app.tasks.download.resolve_url.apply_async") as mock_task:
                periodic_playlist_refresh.apply()
        mock_task.assert_not_called()

    def test_skips_when_not_due(self, db):
        from app.tasks.scheduler import periodic_playlist_refresh
        db.add(AppSetting(key="url_sync_interval_minutes", value="60"))
        db.add(AppSetting(key="url_sync_last_run",
                          value=(datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()))
        db.commit()

        with patch("app.tasks.scheduler.SessionLocal", return_value=db):
            with patch("app.tasks.download.resolve_url.apply_async") as mock_task:
                periodic_playlist_refresh.apply()
        mock_task.assert_not_called()

    def test_runs_when_due(self, db):
        from app.models import UrlSource
        from app.tasks.scheduler import periodic_playlist_refresh

        db.add(AppSetting(key="url_sync_interval_minutes", value="60"))
        db.add(AppSetting(key="url_sync_last_run",
                          value=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()))
        db.add(UrlSource(
            url="https://youtube.com/playlist?list=PL1",
            canonical_url="playlist:PL1",
            url_type="playlist",
            sync_enabled=True,
        ))
        db.commit()

        with patch("app.tasks.scheduler.SessionLocal", return_value=db):
            with patch("app.tasks.download.resolve_url.apply_async") as mock_task:
                periodic_playlist_refresh.apply()
        mock_task.assert_called_once()

    def test_updates_last_run_timestamp(self, db):
        from app.tasks.scheduler import periodic_playlist_refresh

        db.add(AppSetting(key="url_sync_interval_minutes", value="60"))
        db.commit()

        with patch("app.tasks.scheduler.SessionLocal", return_value=db):
            periodic_playlist_refresh.apply()

        row = db.get(AppSetting, "url_sync_last_run")
        assert row is not None
        last_run = datetime.fromisoformat(row.value)
        assert (datetime.now(timezone.utc) - last_run.replace(tzinfo=timezone.utc)).total_seconds() < 5


# ── periodic_youtube_playlist_sync ────────────────────────────────────────────

class TestPeriodicYoutubePlaylists:
    def test_skips_when_interval_zero(self, db):
        from app.tasks.scheduler import periodic_youtube_playlist_sync
        db.add(AppSetting(key="youtube_sync_interval_minutes", value="0"))
        db.commit()

        with patch("app.tasks.scheduler.SessionLocal", return_value=db):
            with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async") as mock_task:
                periodic_youtube_playlist_sync.apply()
        mock_task.assert_not_called()

    def test_skips_when_not_due(self, db):
        from app.tasks.scheduler import periodic_youtube_playlist_sync
        db.add(AppSetting(key="youtube_sync_interval_minutes", value="60"))
        db.add(AppSetting(key="youtube_sync_last_run",
                          value=(datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()))
        db.commit()

        with patch("app.tasks.scheduler.SessionLocal", return_value=db):
            with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async") as mock_task:
                periodic_youtube_playlist_sync.apply()
        mock_task.assert_not_called()

    def test_runs_when_due(self, db):
        from app.models import YoutubePlaylistSync
        from app.tasks.scheduler import periodic_youtube_playlist_sync

        db.add(AppSetting(key="youtube_sync_interval_minutes", value="60"))
        db.add(YoutubePlaylistSync(playlist_id="PL1", playlist_name="My List", enabled=True))
        db.commit()

        with patch("app.tasks.scheduler.SessionLocal", return_value=db):
            with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async") as mock_task:
                periodic_youtube_playlist_sync.apply()
        mock_task.assert_called_once()

    def test_updates_last_run_timestamp(self, db):
        from app.tasks.scheduler import periodic_youtube_playlist_sync

        db.add(AppSetting(key="youtube_sync_interval_minutes", value="60"))
        db.commit()

        with patch("app.tasks.scheduler.SessionLocal", return_value=db):
            periodic_youtube_playlist_sync.apply()

        row = db.get(AppSetting, "youtube_sync_last_run")
        assert row is not None


def test_update_download_gain_percent(client):
    resp = client.patch("/api/v1/settings", json={"download_gain_percent": 35.5})
    assert resp.status_code == 200
    assert resp.json()["download_gain_percent"] == 35.5


def test_negative_gain_rejected(client):
    resp = client.patch("/api/v1/settings", json={"download_gain_percent": -1})
    assert resp.status_code == 422


def test_update_silence_trim_secs(client):
    with patch("app.tasks.maintenance.requeue_silence_trim_changed.apply_async"):
        resp = client.patch("/api/v1/settings", json={
            "silence_trim_start_secs": 3.0,
            "silence_trim_end_secs": 1.5,
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["silence_trim_start_secs"] == 3.0
    assert data["silence_trim_end_secs"] == 1.5


def test_silence_trim_zero_disables(client):
    with patch("app.tasks.maintenance.retrim_existing_silence_locally.apply_async"):
        resp = client.patch("/api/v1/settings", json={
            "silence_trim_start_secs": 0,
            "silence_trim_end_secs": 0,
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["silence_trim_start_secs"] == 0.0
    assert data["silence_trim_end_secs"] == 0.0


def test_negative_silence_trim_rejected(client):
    resp = client.patch("/api/v1/settings", json={"silence_trim_start_secs": -1})
    assert resp.status_code == 422
    resp = client.patch("/api/v1/settings", json={"silence_trim_end_secs": -1})
    assert resp.status_code == 422


# ── Hybrid re-processing trigger on silence-trim setting change ───────────────
# Increasing the threshold loses previously-removed audio for good, so it needs
# a full redownload. Decreasing it leaves the residual silence physically intact
# locally, so it can be retrimmed in place without contacting YouTube.

def test_silence_trim_increase_triggers_requeue(client):
    with patch("app.tasks.maintenance.requeue_silence_trim_changed.apply_async") as mock_requeue:
        with patch("app.tasks.maintenance.retrim_existing_silence_locally.apply_async") as mock_retrim:
            resp = client.patch("/api/v1/settings", json={"silence_trim_start_secs": 4.0})
    assert resp.status_code == 200
    mock_requeue.assert_called_once()
    mock_retrim.assert_not_called()
    assert resp.json()["silence_trim_requeued"] is True
    assert resp.json()["silence_trim_retrimmed_locally"] is False


def test_silence_trim_decrease_triggers_local_retrim(client):
    with patch("app.tasks.maintenance.requeue_silence_trim_changed.apply_async") as mock_requeue:
        with patch("app.tasks.maintenance.retrim_existing_silence_locally.apply_async") as mock_retrim:
            resp = client.patch("/api/v1/settings", json={"silence_trim_start_secs": 1.0})
    assert resp.status_code == 200
    mock_requeue.assert_not_called()
    mock_retrim.assert_called_once()
    assert resp.json()["silence_trim_requeued"] is False
    assert resp.json()["silence_trim_retrimmed_locally"] is True


def test_silence_trim_mixed_increase_and_decrease_prefers_requeue(client):
    # start increases (2.5 -> 3.0), end decreases (2.5 -> 1.5): the redownload
    # path wins since it also re-applies the decrease using the latest settings.
    with patch("app.tasks.maintenance.requeue_silence_trim_changed.apply_async") as mock_requeue:
        with patch("app.tasks.maintenance.retrim_existing_silence_locally.apply_async") as mock_retrim:
            resp = client.patch("/api/v1/settings", json={
                "silence_trim_start_secs": 3.0,
                "silence_trim_end_secs": 1.5,
            })
    assert resp.status_code == 200
    mock_requeue.assert_called_once()
    mock_retrim.assert_not_called()
    assert resp.json()["silence_trim_requeued"] is True
    assert resp.json()["silence_trim_retrimmed_locally"] is False


def test_silence_trim_unchanged_value_triggers_nothing(client):
    with patch("app.tasks.maintenance.requeue_silence_trim_changed.apply_async") as mock_requeue:
        with patch("app.tasks.maintenance.retrim_existing_silence_locally.apply_async") as mock_retrim:
            resp = client.patch("/api/v1/settings", json={"silence_trim_start_secs": 2.5})
    mock_requeue.assert_not_called()
    mock_retrim.assert_not_called()
    assert resp.json()["silence_trim_requeued"] is False
    assert resp.json()["silence_trim_retrimmed_locally"] is False


def test_unrelated_setting_change_triggers_nothing(client):
    with patch("app.tasks.maintenance.requeue_silence_trim_changed.apply_async") as mock_requeue:
        with patch("app.tasks.maintenance.retrim_existing_silence_locally.apply_async") as mock_retrim:
            client.patch("/api/v1/settings", json={"download_gain_percent": 15})
    mock_requeue.assert_not_called()
    mock_retrim.assert_not_called()


def test_update_ffmpeg_threads(client):
    resp = client.patch("/api/v1/settings", json={"ffmpeg_threads": 3})
    assert resp.status_code == 200
    assert resp.json()["ffmpeg_threads"] == 3


def test_negative_ffmpeg_threads_rejected(client):
    resp = client.patch("/api/v1/settings", json={"ffmpeg_threads": -1})
    assert resp.status_code == 422


def test_update_ffmpeg_memory_limit(client):
    resp = client.patch("/api/v1/settings", json={"ffmpeg_memory_limit_mb": 512})
    assert resp.status_code == 200
    assert resp.json()["ffmpeg_memory_limit_mb"] == 512


def test_negative_ffmpeg_memory_limit_rejected(client):
    resp = client.patch("/api/v1/settings", json={"ffmpeg_memory_limit_mb": -1})
    assert resp.status_code == 422


def test_update_celery_worker_concurrency(client):
    resp = client.patch("/api/v1/settings", json={"celery_worker_concurrency": 4})
    assert resp.status_code == 200
    assert resp.json()["celery_worker_concurrency"] == 4


def test_zero_celery_worker_concurrency_means_auto(client):
    resp = client.patch("/api/v1/settings", json={"celery_worker_concurrency": 0})
    assert resp.status_code == 200
    assert resp.json()["celery_worker_concurrency"] == 0


def test_negative_celery_worker_concurrency_rejected(client):
    resp = client.patch("/api/v1/settings", json={"celery_worker_concurrency": -1})
    assert resp.status_code == 422


def test_update_discord_webhook_url(client):
    url = "https://discord.com/api/webhooks/123/abc"
    resp = client.patch("/api/v1/settings", json={"discord_webhook_url": url})
    assert resp.status_code == 200
    assert resp.json()["discord_webhook_url"] == url


def test_clear_discord_webhook_url(client):
    client.patch("/api/v1/settings", json={"discord_webhook_url": "https://discord.com/api/webhooks/123/abc"})
    resp = client.patch("/api/v1/settings", json={"discord_webhook_url": ""})
    assert resp.status_code == 200
    assert resp.json()["discord_webhook_url"] == ""


def test_get_settings_includes_new_fields(client):
    data = client.get("/api/v1/settings").json()
    assert "celery_worker_concurrency" in data
    assert "discord_webhook_url" in data
    assert data["celery_worker_concurrency"] == 0
    assert data["discord_webhook_url"] == ""


# ── Notification settings ─────────────────────────────────────────────────────

def test_get_settings_notification_defaults(client):
    data = client.get("/api/v1/settings").json()
    assert data["notify_on_download_complete"] is False
    assert data["notify_on_download_failed"] is True
    assert data["notify_on_db_error"] is True
    assert data["notify_on_youtube_auth_expired"] is True


def test_update_notification_flags(client):
    resp = client.patch("/api/v1/settings", json={
        "notify_on_download_complete": True,
        "notify_on_download_failed": False,
        "notify_on_db_error": False,
        "notify_on_youtube_auth_expired": False,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["notify_on_download_complete"] is True
    assert data["notify_on_download_failed"] is False
    assert data["notify_on_db_error"] is False
    assert data["notify_on_youtube_auth_expired"] is False


def test_notification_flags_persist(client):
    client.patch("/api/v1/settings", json={"notify_on_download_complete": True})
    data = client.get("/api/v1/settings").json()
    assert data["notify_on_download_complete"] is True


def test_partial_notification_update_leaves_others_unchanged(client):
    client.patch("/api/v1/settings", json={"notify_on_download_complete": True})
    data = client.get("/api/v1/settings").json()
    assert data["notify_on_download_failed"] is True   # default unchanged
    assert data["notify_on_download_complete"] is True


def test_notification_flags_stored_as_lowercase_string(client, db):
    from app.models import AppSetting
    client.patch("/api/v1/settings", json={"notify_on_download_complete": True})
    row = db.get(AppSetting, "notify_on_download_complete")
    assert row is not None
    assert row.value == "true"

    client.patch("/api/v1/settings", json={"notify_on_download_complete": False})
    db.expire(row)
    row = db.get(AppSetting, "notify_on_download_complete")
    assert row.value == "false"


# ── OAuth expiry warning settings ─────────────────────────────────────────────

def test_get_settings_oauth_expiry_defaults(client):
    data = client.get("/api/v1/settings").json()
    assert data["notify_on_oauth_expiry_warning"] is True
    assert data["oauth_expiry_warning_minutes"] == 60


def test_update_oauth_expiry_warning_flag(client):
    resp = client.patch("/api/v1/settings", json={"notify_on_oauth_expiry_warning": False})
    assert resp.status_code == 200
    assert resp.json()["notify_on_oauth_expiry_warning"] is False


def test_update_oauth_expiry_warning_minutes(client):
    resp = client.patch("/api/v1/settings", json={"oauth_expiry_warning_minutes": 30})
    assert resp.status_code == 200
    assert resp.json()["oauth_expiry_warning_minutes"] == 30


def test_oauth_expiry_warning_minutes_zero_rejected(client):
    resp = client.patch("/api/v1/settings", json={"oauth_expiry_warning_minutes": 0})
    assert resp.status_code == 422


def test_oauth_expiry_warning_minutes_negative_rejected(client):
    resp = client.patch("/api/v1/settings", json={"oauth_expiry_warning_minutes": -10})
    assert resp.status_code == 422


# ── periodic_oauth_expiry_check ───────────────────────────────────────────────

class TestOAuthExpiryCheck:
    def _token(self, db, expiry):
        from app.models import YouTubeOAuthToken
        db.add(YouTubeOAuthToken(
            access_token="token",
            refresh_token="refresh",
            token_expiry=expiry,
        ))
        db.commit()

    def test_does_nothing_when_no_token(self, db):
        from app.tasks.scheduler import periodic_oauth_expiry_check
        from app.models import AppSetting
        db.add(AppSetting(key="oauth_expiry_warning_minutes", value="60"))
        db.commit()

        with patch("app.tasks.scheduler.SessionLocal", return_value=db):
            with patch("app.services.notification.notify") as mock_notify:
                periodic_oauth_expiry_check.apply()
        mock_notify.assert_not_called()

    def test_does_nothing_when_threshold_zero(self, db):
        from datetime import datetime, timezone, timedelta
        from app.tasks.scheduler import periodic_oauth_expiry_check
        from app.models import AppSetting
        db.add(AppSetting(key="oauth_expiry_warning_minutes", value="0"))
        db.commit()
        self._token(db, datetime.now(timezone.utc) + timedelta(minutes=30))

        with patch("app.tasks.scheduler.SessionLocal", return_value=db):
            with patch("app.services.notification.notify") as mock_notify:
                periodic_oauth_expiry_check.apply()
        mock_notify.assert_not_called()

    def test_notifies_when_within_threshold(self, db):
        from datetime import datetime, timezone, timedelta
        from app.tasks.scheduler import periodic_oauth_expiry_check
        from app.models import AppSetting
        db.add(AppSetting(key="oauth_expiry_warning_minutes", value="60"))
        db.commit()
        self._token(db, datetime.now(timezone.utc) + timedelta(minutes=30))

        with patch("app.tasks.scheduler.SessionLocal", return_value=db):
            with patch("app.services.notification.notify") as mock_notify:
                periodic_oauth_expiry_check.apply()
        mock_notify.assert_called_once()
        assert mock_notify.call_args[0][0] == "notify_on_oauth_expiry_warning"
        assert "分" in mock_notify.call_args[0][2]  # remaining minutes in message

    def test_does_not_notify_when_outside_threshold(self, db):
        from datetime import datetime, timezone, timedelta
        from app.tasks.scheduler import periodic_oauth_expiry_check
        from app.models import AppSetting
        db.add(AppSetting(key="oauth_expiry_warning_minutes", value="60"))
        db.commit()
        self._token(db, datetime.now(timezone.utc) + timedelta(hours=3))

        with patch("app.tasks.scheduler.SessionLocal", return_value=db):
            with patch("app.services.notification.notify") as mock_notify:
                periodic_oauth_expiry_check.apply()
        mock_notify.assert_not_called()

    def test_does_not_notify_when_already_expired(self, db):
        from datetime import datetime, timezone, timedelta
        from app.tasks.scheduler import periodic_oauth_expiry_check
        from app.models import AppSetting
        db.add(AppSetting(key="oauth_expiry_warning_minutes", value="60"))
        db.commit()
        self._token(db, datetime.now(timezone.utc) - timedelta(minutes=5))

        with patch("app.tasks.scheduler.SessionLocal", return_value=db):
            with patch("app.services.notification.notify") as mock_notify:
                periodic_oauth_expiry_check.apply()
        mock_notify.assert_not_called()

    def test_does_not_spam_for_same_expiry(self, db):
        from datetime import datetime, timezone, timedelta
        from app.tasks.scheduler import periodic_oauth_expiry_check
        from app.models import AppSetting
        expiry = datetime.now(timezone.utc) + timedelta(minutes=30)
        db.add(AppSetting(key="oauth_expiry_warning_minutes", value="60"))
        db.add(AppSetting(key="oauth_expiry_last_notified_expiry", value=expiry.isoformat()))
        db.commit()
        self._token(db, expiry)

        with patch("app.tasks.scheduler.SessionLocal", return_value=db):
            with patch("app.services.notification.notify") as mock_notify:
                periodic_oauth_expiry_check.apply()
        mock_notify.assert_not_called()

    def test_records_notified_expiry_after_notification(self, db):
        from datetime import datetime, timezone, timedelta
        from app.tasks.scheduler import periodic_oauth_expiry_check
        from app.models import AppSetting
        expiry = datetime.now(timezone.utc) + timedelta(minutes=30)
        db.add(AppSetting(key="oauth_expiry_warning_minutes", value="60"))
        db.commit()
        self._token(db, expiry)

        with patch("app.tasks.scheduler.SessionLocal", return_value=db):
            with patch("app.services.notification.notify"):
                periodic_oauth_expiry_check.apply()

        row = db.get(AppSetting, "oauth_expiry_last_notified_expiry")
        assert row is not None and row.value != ""
