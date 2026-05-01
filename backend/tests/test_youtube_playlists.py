"""Tests for YouTube playlist sync: OAuth endpoints, sync CRUD, task logic."""
import os
import tempfile
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.models import AppSetting, PlaylistSyncTrack, YouTubeOAuthToken, YoutubePlaylistSync


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_token(db, access_token="tok", refresh_token="ref", expires_in=3600) -> YouTubeOAuthToken:
    record = YouTubeOAuthToken(
        access_token=access_token,
        refresh_token=refresh_token,
        token_expiry=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
        scope="https://www.googleapis.com/auth/youtube.readonly",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _make_sync(db, playlist_id="PLabc", playlist_name="My List", enabled=True) -> YoutubePlaylistSync:
    sync = YoutubePlaylistSync(
        playlist_id=playlist_id,
        playlist_name=playlist_name,
        audio_format="mp3",
        audio_quality="192",
        enabled=enabled,
    )
    db.add(sync)
    db.commit()
    db.refresh(sync)
    return sync


def _make_track(db, sync: YoutubePlaylistSync, youtube_id="vid1", status="complete", file_path="/playlists/test.mp3") -> PlaylistSyncTrack:
    track = PlaylistSyncTrack(
        playlist_sync_id=sync.id,
        youtube_id=youtube_id,
        title="Test Track",
        artist="Test Artist",
        duration_secs=180,
        position=0,
        status=status,
        file_path=file_path,
        file_format="mp3",
    )
    db.add(track)
    db.commit()
    db.refresh(track)
    return track


# ── OAuth endpoints ───────────────────────────────────────────────────────────

class TestAuthUrl:
    def test_returns_url_when_configured(self, client):
        with patch("app.config.settings.youtube_client_id", "client123"):
            with patch("app.services.youtube_api_service.get_auth_url", return_value="https://accounts.google.com/o/oauth2/v2/auth?foo=bar"):
                resp = client.get("/api/v1/youtube/auth/url")
        assert resp.status_code == 200
        assert "url" in resp.json()

    def test_returns_400_when_not_configured(self, client):
        with patch("app.api.youtube_playlists.settings") as mock_settings:
            mock_settings.youtube_client_id = ""
            resp = client.get("/api/v1/youtube/auth/url")
        assert resp.status_code == 400


class TestAuthStatus:
    def test_not_authenticated(self, client):
        resp = client.get("/api/v1/youtube/auth/status")
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False

    def test_authenticated(self, client, db):
        _make_token(db)
        resp = client.get("/api/v1/youtube/auth/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is True
        assert "youtube.readonly" in data["scope"]


class TestAuthRevoke:
    def test_revoke_no_token(self, client):
        resp = client.delete("/api/v1/youtube/auth")
        assert resp.status_code == 204

    def test_revoke_existing_token(self, client, db):
        _make_token(db)
        with patch("app.services.youtube_api_service.revoke_token"):
            resp = client.delete("/api/v1/youtube/auth")
        assert resp.status_code == 204
        assert db.query(YouTubeOAuthToken).count() == 0

    def test_revoke_ignores_api_error(self, client, db):
        _make_token(db)
        with patch("app.services.youtube_api_service.revoke_token", side_effect=Exception("network error")):
            resp = client.delete("/api/v1/youtube/auth")
        assert resp.status_code == 204
        assert db.query(YouTubeOAuthToken).count() == 0


class TestOAuthCallback:
    def test_callback_stores_token(self, client, db):
        fake_token_data = {
            "access_token": "new_access",
            "refresh_token": "new_refresh",
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/youtube.readonly",
        }
        with patch("app.api.youtube_playlists.settings") as mock_settings:
            mock_settings.youtube_client_id = "id"
            mock_settings.youtube_client_secret = "secret"
            mock_settings.youtube_redirect_uri = "http://localhost/cb"
            with patch("app.services.youtube_api_service.exchange_code", return_value=fake_token_data):
                resp = client.get("/api/v1/youtube/auth/callback?code=authcode123", follow_redirects=False)
        assert resp.status_code in (302, 307)
        assert db.query(YouTubeOAuthToken).count() == 1
        token = db.query(YouTubeOAuthToken).first()
        assert token.access_token == "new_access"

    def test_callback_updates_existing_token(self, client, db):
        _make_token(db, access_token="old_access", refresh_token="old_refresh")
        new_data = {
            "access_token": "updated_access",
            "refresh_token": "updated_refresh",
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/youtube.readonly",
        }
        with patch("app.api.youtube_playlists.settings") as mock_settings:
            mock_settings.youtube_client_id = "id"
            mock_settings.youtube_client_secret = "secret"
            mock_settings.youtube_redirect_uri = "http://localhost/cb"
            with patch("app.services.youtube_api_service.exchange_code", return_value=new_data):
                client.get("/api/v1/youtube/auth/callback?code=newcode", follow_redirects=False)
        assert db.query(YouTubeOAuthToken).count() == 1
        assert db.query(YouTubeOAuthToken).first().access_token == "updated_access"

    def test_callback_returns_400_on_exchange_failure(self, client, db):
        with patch("app.api.youtube_playlists.settings") as mock_settings:
            mock_settings.youtube_client_id = "id"
            mock_settings.youtube_client_secret = "secret"
            mock_settings.youtube_redirect_uri = "http://localhost/cb"
            with patch("app.services.youtube_api_service.exchange_code", side_effect=Exception("bad code")):
                resp = client.get("/api/v1/youtube/auth/callback?code=bad")
        assert resp.status_code == 400


# ── Account playlists ─────────────────────────────────────────────────────────

class TestListAccountPlaylists:
    def test_requires_auth(self, client):
        resp = client.get("/api/v1/youtube/playlists")
        assert resp.status_code == 401

    def test_returns_playlist_list(self, client, db):
        _make_token(db)
        fake_playlists = [
            {"playlist_id": "PL1", "title": "Chill Vibes", "item_count": 12, "thumbnail_url": None},
            {"playlist_id": "PL2", "title": "Workout", "item_count": 25, "thumbnail_url": "https://img/thumb.jpg"},
        ]
        with patch("app.services.youtube_api_service.get_fresh_access_token", return_value="tok"):
            with patch("app.services.youtube_api_service.get_my_playlists", return_value=fake_playlists):
                resp = client.get("/api/v1/youtube/playlists")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["playlist_id"] == "PL1"
        assert data[1]["item_count"] == 25

    def test_returns_502_on_api_error(self, client, db):
        _make_token(db)
        with patch("app.services.youtube_api_service.get_fresh_access_token", return_value="tok"):
            with patch("app.services.youtube_api_service.get_my_playlists", side_effect=Exception("quota exceeded")):
                resp = client.get("/api/v1/youtube/playlists")
        assert resp.status_code == 502


# ── Sync CRUD ─────────────────────────────────────────────────────────────────

class TestListSyncs:
    def test_empty(self, client):
        resp = client.get("/api/v1/youtube/syncs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_syncs_with_counts(self, client, db):
        sync = _make_sync(db)
        _make_track(db, sync, youtube_id="v1", status="complete")
        _make_track(db, sync, youtube_id="v2", status="pending")
        _make_track(db, sync, youtube_id="v3", status="removed")

        resp = client.get("/api/v1/youtube/syncs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["playlist_id"] == "PLabc"
        assert data[0]["track_count"] == 2       # excludes removed
        assert data[0]["downloaded_count"] == 1  # only complete


class TestCreateSync:
    def test_create_sync(self, client):
        with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async"):
            resp = client.post("/api/v1/youtube/syncs", json={
                "playlist_id": "PLnew",
                "playlist_name": "New Playlist",
                "audio_format": "mp3",
                "audio_quality": "320",
                "enabled": True,
            })
        assert resp.status_code == 201
        data = resp.json()
        assert data["playlist_id"] == "PLnew"
        assert data["audio_quality"] == "320"
        assert data["enabled"] is True

    def test_create_sync_triggers_initial_sync(self, client):
        with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async") as mock_task:
            client.post("/api/v1/youtube/syncs", json={
                "playlist_id": "PLinit",
                "playlist_name": "Init Playlist",
                "enabled": True,
            })
        mock_task.assert_called_once()

    def test_create_sync_disabled_skips_initial_sync(self, client):
        with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async") as mock_task:
            client.post("/api/v1/youtube/syncs", json={
                "playlist_id": "PLdisabled",
                "playlist_name": "Disabled",
                "enabled": False,
            })
        mock_task.assert_not_called()

    def test_duplicate_playlist_id_rejected(self, client, db):
        _make_sync(db, playlist_id="PLdup")
        with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async"):
            resp = client.post("/api/v1/youtube/syncs", json={
                "playlist_id": "PLdup",
                "playlist_name": "Dup",
            })
        assert resp.status_code == 409


class TestUpdateSync:
    def test_update_format_and_quality(self, client, db):
        sync = _make_sync(db)
        resp = client.patch(f"/api/v1/youtube/syncs/{sync.id}", json={
            "audio_format": "flac",
            "audio_quality": "best",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["audio_format"] == "flac"
        assert data["audio_quality"] == "best"
        assert data["playlist_name"] == "My List"  # unchanged

    def test_disable_sync(self, client, db):
        sync = _make_sync(db, enabled=True)
        resp = client.patch(f"/api/v1/youtube/syncs/{sync.id}", json={"enabled": False})
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    def test_update_not_found(self, client):
        resp = client.patch("/api/v1/youtube/syncs/999", json={"enabled": False})
        assert resp.status_code == 404


class TestDeleteSync:
    def test_delete_sync(self, client, db):
        sync = _make_sync(db)
        resp = client.delete(f"/api/v1/youtube/syncs/{sync.id}")
        assert resp.status_code == 204
        assert db.query(YoutubePlaylistSync).count() == 0

    def test_delete_not_found(self, client):
        resp = client.delete("/api/v1/youtube/syncs/999")
        assert resp.status_code == 404

    def test_delete_cascades_tracks(self, client, db):
        sync = _make_sync(db)
        _make_track(db, sync)
        client.delete(f"/api/v1/youtube/syncs/{sync.id}")
        assert db.query(PlaylistSyncTrack).count() == 0

    def test_delete_with_files(self, client, db):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
            tmp_path = f.name
        try:
            sync = _make_sync(db)
            _make_track(db, sync, file_path=tmp_path)
            resp = client.delete(f"/api/v1/youtube/syncs/{sync.id}?delete_files=true")
            assert resp.status_code == 204
            assert not os.path.exists(tmp_path)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


class TestSyncNow:
    def test_sync_now_requires_auth(self, client, db):
        sync = _make_sync(db)
        with patch("app.services.youtube_api_service.get_fresh_access_token", return_value=None):
            resp = client.post(f"/api/v1/youtube/syncs/{sync.id}/run")
        assert resp.status_code == 401

    def test_sync_now_queues_task(self, client, db):
        _make_token(db)
        sync = _make_sync(db)
        with patch("app.services.youtube_api_service.get_fresh_access_token", return_value="tok"):
            with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async") as mock_task:
                resp = client.post(f"/api/v1/youtube/syncs/{sync.id}/run")
        assert resp.status_code == 202
        assert resp.json()["queued"] is True
        mock_task.assert_called_once_with(args=[sync.id])

    def test_sync_now_not_found(self, client):
        resp = client.post("/api/v1/youtube/syncs/999/run")
        assert resp.status_code == 404


# ── Sync tracks ───────────────────────────────────────────────────────────────

class TestListSyncTracks:
    def test_list_tracks(self, client, db):
        sync = _make_sync(db)
        _make_track(db, sync, youtube_id="v1", status="complete")
        _make_track(db, sync, youtube_id="v2", status="pending")
        _make_track(db, sync, youtube_id="v3", status="removed")

        resp = client.get(f"/api/v1/youtube/syncs/{sync.id}/tracks")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2  # removed is excluded
        statuses = {t["status"] for t in data}
        assert "removed" not in statuses

    def test_complete_track_has_stream_url(self, client, db):
        sync = _make_sync(db)
        _make_track(db, sync, status="complete")
        data = client.get(f"/api/v1/youtube/syncs/{sync.id}/tracks").json()
        assert data[0]["stream_url"] is not None
        assert "stream" in data[0]["stream_url"]

    def test_pending_track_has_no_stream_url(self, client, db):
        sync = _make_sync(db)
        _make_track(db, sync, status="pending", file_path=None)
        data = client.get(f"/api/v1/youtube/syncs/{sync.id}/tracks").json()
        assert data[0]["stream_url"] is None

    def test_not_found(self, client):
        resp = client.get("/api/v1/youtube/syncs/999/tracks")
        assert resp.status_code == 404


class TestStreamSyncTrack:
    def test_stream_not_found(self, client):
        resp = client.get("/api/v1/youtube/syncs/tracks/999/stream")
        assert resp.status_code == 404

    def test_stream_no_file_path(self, client, db):
        sync = _make_sync(db)
        track = _make_track(db, sync, status="pending", file_path=None)
        resp = client.get(f"/api/v1/youtube/syncs/tracks/{track.id}/stream")
        assert resp.status_code == 404

    def test_stream_file_missing_on_disk(self, client, db):
        sync = _make_sync(db)
        track = _make_track(db, sync, file_path="/nonexistent/file.mp3")
        resp = client.get(f"/api/v1/youtube/syncs/tracks/{track.id}/stream")
        assert resp.status_code == 404

    def test_stream_returns_audio(self, client, db):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
            f.write(b"\xff\xfb" + b"\x00" * 128)
            tmp_path = f.name
        try:
            sync = _make_sync(db)
            track = _make_track(db, sync, file_path=tmp_path)
            resp = client.get(f"/api/v1/youtube/syncs/tracks/{track.id}/stream")
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "audio/mpeg"
        finally:
            os.unlink(tmp_path)


# ── youtube_api_service unit tests ────────────────────────────────────────────

class TestYouTubeApiService:
    def test_get_auth_url_contains_client_id(self):
        from app.services import youtube_api_service
        with patch("app.services.youtube_api_service.settings") as mock_settings:
            mock_settings.youtube_client_id = "my_client_id"
            mock_settings.youtube_redirect_uri = "http://localhost/cb"
            url = youtube_api_service.get_auth_url()
        assert "my_client_id" in url
        assert "accounts.google.com" in url
        assert "youtube.readonly" in url

    def test_get_fresh_access_token_returns_none_if_no_record(self, db):
        from app.services.youtube_api_service import get_fresh_access_token
        assert get_fresh_access_token(db) is None

    def test_get_fresh_access_token_returns_valid_token(self, db):
        from app.services.youtube_api_service import get_fresh_access_token
        _make_token(db, access_token="valid_tok", expires_in=3600)
        assert get_fresh_access_token(db) == "valid_tok"

    def test_get_fresh_access_token_refreshes_expired(self, db):
        from app.services.youtube_api_service import get_fresh_access_token
        expired = YouTubeOAuthToken(
            access_token="expired_tok",
            refresh_token="ref_tok",
            token_expiry=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        db.add(expired)
        db.commit()

        new_token_data = {"access_token": "refreshed_tok", "expires_in": 3600}
        with patch("app.services.youtube_api_service.refresh_access_token", return_value=new_token_data):
            result = get_fresh_access_token(db)
        assert result == "refreshed_tok"

    def test_get_my_playlists_paginates(self):
        from app.services.youtube_api_service import get_my_playlists

        def fake_get(url, params, headers):
            page = params.get("pageToken")
            if page is None:
                return MagicMock(
                    status_code=200,
                    json=lambda: {
                        "items": [{"id": "PL1", "snippet": {"title": "List 1", "thumbnails": {}}, "contentDetails": {"itemCount": 5}}],
                        "nextPageToken": "PAGE2",
                    },
                    raise_for_status=lambda: None,
                )
            return MagicMock(
                status_code=200,
                json=lambda: {
                    "items": [{"id": "PL2", "snippet": {"title": "List 2", "thumbnails": {}}, "contentDetails": {"itemCount": 3}}],
                },
                raise_for_status=lambda: None,
            )

        with patch("app.services.youtube_api_service.httpx.get", side_effect=fake_get):
            result = get_my_playlists("tok")

        assert len(result) == 2
        assert result[0]["playlist_id"] == "PL1"
        assert result[1]["playlist_id"] == "PL2"

    def test_get_playlist_items_skips_missing_video_id(self):
        from app.services.youtube_api_service import get_playlist_items

        fake_resp = MagicMock(
            json=lambda: {
                "items": [
                    {"snippet": {"resourceId": {"videoId": "vid1"}, "title": "Track 1", "thumbnails": {}}},
                    {"snippet": {"resourceId": {}, "title": "Bad Item", "thumbnails": {}}},
                ]
            },
            raise_for_status=lambda: None,
        )
        with patch("app.services.youtube_api_service.httpx.get", return_value=fake_resp):
            items = get_playlist_items("PL1", "tok")
        assert len(items) == 1
        assert items[0]["youtube_id"] == "vid1"


# ── Celery task unit tests ────────────────────────────────────────────────────

class TestSyncYoutubePlaylistTask:
    def test_skips_disabled_sync(self, db):
        from app.tasks.sync_playlist import sync_youtube_playlist
        sync = _make_sync(db, enabled=False)

        with patch("app.database.SessionLocal", return_value=db):
            sync_youtube_playlist.apply(args=[sync.id])

        assert db.get(YoutubePlaylistSync, sync.id).last_synced is None

    def test_skips_when_no_access_token(self, db):
        from app.tasks.sync_playlist import sync_youtube_playlist
        sync = _make_sync(db)

        with patch("app.database.SessionLocal", return_value=db):
            with patch("app.services.youtube_api_service.get_fresh_access_token", return_value=None):
                sync_youtube_playlist.apply(args=[sync.id])

        assert db.get(YoutubePlaylistSync, sync.id).last_synced is None

    def test_downloads_new_tracks(self, db):
        from app.tasks.sync_playlist import sync_youtube_playlist
        sync = _make_sync(db)

        remote_items = [
            {"youtube_id": "newvid1", "title": "New Song", "position": 0, "thumbnail_url": None},
        ]
        with patch("app.database.SessionLocal", return_value=db):
            with patch("app.services.youtube_api_service.get_fresh_access_token", return_value="tok"):
                with patch("app.services.youtube_api_service.get_playlist_items", return_value=remote_items):
                    with patch("app.tasks.sync_playlist.download_playlist_sync_track.apply_async") as mock_dl:
                        sync_youtube_playlist.apply(args=[sync.id])

        mock_dl.assert_called_once()
        track = db.query(PlaylistSyncTrack).filter_by(youtube_id="newvid1").first()
        assert track is not None
        assert track.status == "pending"

    def test_marks_removed_tracks(self, db):
        from app.tasks.sync_playlist import sync_youtube_playlist
        sync = _make_sync(db)
        track = _make_track(db, sync, youtube_id="old_vid", status="complete")

        with patch("app.database.SessionLocal", return_value=db):
            with patch("app.services.youtube_api_service.get_fresh_access_token", return_value="tok"):
                with patch("app.services.youtube_api_service.get_playlist_items", return_value=[]):
                    with patch("app.tasks.sync_playlist._delete_sync_track_file"):
                        sync_youtube_playlist.apply(args=[sync.id])

        db.refresh(track)
        assert track.status == "removed"

    def test_re_downloads_previously_removed_track(self, db):
        from app.tasks.sync_playlist import sync_youtube_playlist
        sync = _make_sync(db)
        track = _make_track(db, sync, youtube_id="revived_vid", status="removed", file_path=None)

        remote_items = [{"youtube_id": "revived_vid", "title": "Revived", "position": 0, "thumbnail_url": None}]
        with patch("app.database.SessionLocal", return_value=db):
            with patch("app.services.youtube_api_service.get_fresh_access_token", return_value="tok"):
                with patch("app.services.youtube_api_service.get_playlist_items", return_value=remote_items):
                    with patch("app.tasks.sync_playlist.download_playlist_sync_track.apply_async") as mock_dl:
                        sync_youtube_playlist.apply(args=[sync.id])

        db.refresh(track)
        assert track.status == "pending"
        mock_dl.assert_called_once()

    def test_does_not_re_download_existing_complete_track(self, db):
        from app.tasks.sync_playlist import sync_youtube_playlist
        sync = _make_sync(db)
        _make_track(db, sync, youtube_id="existing_vid", status="complete")

        remote_items = [{"youtube_id": "existing_vid", "title": "Existing", "position": 0, "thumbnail_url": None}]
        with patch("app.database.SessionLocal", return_value=db):
            with patch("app.services.youtube_api_service.get_fresh_access_token", return_value="tok"):
                with patch("app.services.youtube_api_service.get_playlist_items", return_value=remote_items):
                    with patch("app.tasks.sync_playlist.download_playlist_sync_track.apply_async") as mock_dl:
                        sync_youtube_playlist.apply(args=[sync.id])

        mock_dl.assert_not_called()

    def test_updates_last_synced(self, db):
        from app.tasks.sync_playlist import sync_youtube_playlist
        sync = _make_sync(db)
        assert sync.last_synced is None

        with patch("app.database.SessionLocal", return_value=db):
            with patch("app.services.youtube_api_service.get_fresh_access_token", return_value="tok"):
                with patch("app.services.youtube_api_service.get_playlist_items", return_value=[]):
                    sync_youtube_playlist.apply(args=[sync.id])

        db.refresh(sync)
        assert sync.last_synced is not None


class TestDeleteSyncTrackFile:
    def test_deletes_audio_and_thumbnail(self):
        from app.tasks.sync_playlist import _delete_sync_track_file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as af:
            audio_path = af.name
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tf:
            thumb_path = tf.name
        try:
            track = MagicMock(file_path=audio_path, thumbnail_path=thumb_path)
            _delete_sync_track_file(track)
            assert not os.path.exists(audio_path)
            assert not os.path.exists(thumb_path)
        finally:
            for p in [audio_path, thumb_path]:
                if os.path.exists(p):
                    os.unlink(p)

    def test_handles_already_missing_file(self):
        from app.tasks.sync_playlist import _delete_sync_track_file
        track = MagicMock(file_path="/nonexistent/file.mp3", thumbnail_path=None)
        _delete_sync_track_file(track)  # should not raise


def test_list_sync_tracks_marks_stale_pending_as_failed(client, db):
    sync = YoutubePlaylistSync(
        playlist_id="PLstale",
        playlist_name="Stale Pending",
        audio_format="mp3",
        audio_quality="192",
        enabled=True,
    )
    db.add(sync)
    db.commit()
    db.refresh(sync)

    stale_added_at = datetime.now(timezone.utc) - timedelta(hours=3)
    track = PlaylistSyncTrack(
        playlist_sync_id=sync.id,
        youtube_id="stale123",
        title="Stale Song",
        status="pending",
        added_at=stale_added_at,
        position=1,
    )
    db.add(track)
    db.commit()

    resp = client.get(f"/api/v1/youtube/syncs/{sync.id}/tracks")
    assert resp.status_code == 200

    db.refresh(track)
    assert track.status == "failed"
    assert "pending too long" in (track.error_message or "")


def test_requeued_failed_track_refreshes_added_at_and_stays_pending(client, db):
    from app.tasks.sync_playlist import sync_youtube_playlist

    sync = _make_sync(db)
    stale_added_at = datetime.now(timezone.utc) - timedelta(hours=3)
    track = PlaylistSyncTrack(
        playlist_sync_id=sync.id,
        youtube_id="retry123",
        title="Retry Song",
        status="failed",
        added_at=stale_added_at,
        position=1,
    )
    db.add(track)
    db.commit()

    remote_items = [{"youtube_id": "retry123", "title": "Retry Song", "position": 1, "thumbnail_url": None}]
    with patch("app.database.SessionLocal", return_value=db):
        with patch("app.services.youtube_api_service.get_fresh_access_token", return_value="tok"):
            with patch("app.services.youtube_api_service.get_playlist_items", return_value=remote_items):
                with patch("app.tasks.sync_playlist.download_playlist_sync_track.apply_async"):
                    sync_youtube_playlist.apply(args=[sync.id])

    db.refresh(track)
    assert track.status == "pending"
    stale_naive = stale_added_at.replace(tzinfo=None)
    assert track.added_at > stale_naive

    resp = client.get(f"/api/v1/youtube/syncs/{sync.id}/tracks")
    assert resp.status_code == 200
    db.refresh(track)
    assert track.status == "pending"


class TestDownloadPlaylistSyncTrackTask:
    def test_passes_gain_percent_to_ytdlp_service(self, db):
        from app.tasks.sync_playlist import download_playlist_sync_track

        sync = _make_sync(db)
        track = _make_track(db, sync, youtube_id="vid_gain", status="pending")
        db.add(AppSetting(key="download_gain_percent", value="7.5"))
        db.commit()

        fake_metadata = {
            "youtube_id": "vid_gain",
            "title": "Gain Song",
            "artist": "Artist",
            "duration_secs": 123,
            "file_path": "/tmp/gain.mp3",
            "file_format": "mp3",
            "file_size_bytes": 10,
            "thumbnail_path": None,
        }

        with patch("app.database.SessionLocal", return_value=db):
            with patch("app.tasks.sync_playlist.ytdlp_service.download_track", return_value=fake_metadata) as mock_dl:
                with patch("app.tasks.sync_playlist._redis.delete"):
                    download_playlist_sync_track.apply(args=[track.id])

        _, kwargs = mock_dl.call_args
        assert kwargs["gain_percent"] == 7.5

        db.refresh(track)
        assert track.status == "complete"
