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


def test_get_settings_reflects_db_values(client, db):
    db.add(AppSetting(key="url_sync_interval_minutes", value="30"))
    db.add(AppSetting(key="youtube_sync_interval_minutes", value="180"))
    db.commit()

    data = client.get("/api/v1/settings").json()
    assert data["url_sync_interval_minutes"] == 30
    assert data["youtube_sync_interval_minutes"] == 180


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
        db.add(UrlSource(url="https://youtube.com/playlist?list=PL1", url_type="playlist", sync_enabled=True))
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
