"""Comprehensive tests for:
1. Shared link (URL) and YouTube API sync coexistence
2. mp4/webm download functionality
3. Multiple format specification per playlist
4. Folder naming when multiple formats are used

These tests complement existing coverage in test_youtube_playlists.py and
test_ytdlp_formats.py, focusing on gaps and cross-feature interactions.
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from app.models import PlaylistSyncTrack, YoutubePlaylistSync, YouTubeOAuthToken


# ── Helpers ────────────────────────────────────────────────────────────────────

def _api_sync(db, playlist_id, playlist_name="Test Playlist", audio_format="mp3", dir_name=None):
    sync = YoutubePlaylistSync(
        playlist_id=playlist_id,
        playlist_name=playlist_name,
        source_type="api",
        source_url="",
        audio_format=audio_format,
        audio_quality="192",
        dir_name=dir_name,
        enabled=True,
    )
    db.add(sync)
    db.commit()
    db.refresh(sync)
    return sync


def _url_sync(db, playlist_id, playlist_name="URL Playlist",
              source_url=None, audio_format="mp3", dir_name=None):
    if source_url is None:
        source_url = f"https://www.youtube.com/playlist?list={playlist_id}"
    sync = YoutubePlaylistSync(
        playlist_id=playlist_id,
        playlist_name=playlist_name,
        source_type="url",
        source_url=source_url,
        audio_format=audio_format,
        audio_quality="192",
        dir_name=dir_name,
        enabled=True,
    )
    db.add(sync)
    db.commit()
    db.refresh(sync)
    return sync


def _token(db):
    token = YouTubeOAuthToken(
        access_token="tok",
        refresh_token="ref",
        token_expiry=datetime.now(timezone.utc) + timedelta(hours=1),
        scope="https://www.googleapis.com/auth/youtube.readonly",
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return token


def _track(db, sync, youtube_id, status="pending", file_path=None):
    t = PlaylistSyncTrack(
        playlist_sync_id=sync.id,
        youtube_id=youtube_id,
        title=f"Track {youtube_id}",
        position=1,
        status=status,
        file_path=file_path,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


# ── Feature 1: URL sync and YouTube API sync coexistence ──────────────────────

class TestApiUrlSyncCoexistence:
    """Verify that URL-based and API-based syncs can exist side-by-side."""

    def test_api_and_url_sync_same_playlist_different_format_both_created(self, client, db):
        """Same playlist_id: api/mp3 + url/mp4 can coexist."""
        with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async"):
            r1 = client.post("/api/v1/youtube/syncs", json={
                "playlist_id": "PLcox",
                "playlist_name": "Coexist",
                "source_type": "api",
                "audio_format": "mp3",
            })
        assert r1.status_code == 201

        fake_info = {"playlist_id": "PLcox", "playlist_title": "Coexist", "entries": []}
        with patch("app.api.youtube_playlists.ytdlp_service.get_playlist_info", return_value=fake_info):
            with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async"):
                r2 = client.post("/api/v1/youtube/syncs", json={
                    "source_type": "url",
                    "source_url": "https://www.youtube.com/playlist?list=PLcox",
                    "audio_format": "mp4",
                })
        assert r2.status_code == 201
        assert db.query(YoutubePlaylistSync).filter_by(playlist_id="PLcox").count() == 2

    def test_api_and_url_same_playlist_same_format_rejected(self, client, db):
        """Same playlist + same format is rejected even when source types differ."""
        with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async"):
            client.post("/api/v1/youtube/syncs", json={
                "playlist_id": "PLsame",
                "playlist_name": "Same",
                "source_type": "api",
                "audio_format": "mp3",
            })
        fake_info = {"playlist_id": "PLsame", "playlist_title": "Same", "entries": []}
        with patch("app.api.youtube_playlists.ytdlp_service.get_playlist_info", return_value=fake_info):
            resp = client.post("/api/v1/youtube/syncs", json={
                "source_type": "url",
                "source_url": "https://www.youtube.com/playlist?list=PLsame",
                "audio_format": "mp3",
            })
        assert resp.status_code == 409

    def test_list_returns_both_api_and_url_source_types(self, client, db):
        """GET /syncs lists syncs of both source types."""
        _api_sync(db, "PL_api_list", audio_format="mp3")
        _url_sync(db, "PL_url_list", audio_format="mp4")

        data = client.get("/api/v1/youtube/syncs").json()
        assert len(data) == 2
        source_types = {s["source_type"] for s in data}
        assert source_types == {"api", "url"}

    def test_api_sync_task_calls_youtube_api_not_ytdlp(self, db):
        """API sync task fetches via YouTube Data API and never touches yt-dlp."""
        from app.tasks.sync_playlist import sync_youtube_playlist

        sync = _api_sync(db, "PLapi_task", dir_name="Test Playlist")

        with patch("app.database.SessionLocal", return_value=db):
            with patch("app.services.youtube_api_service.get_fresh_access_token", return_value="tok"):
                with patch("app.services.youtube_api_service.get_playlist_items", return_value=[]) as mock_api:
                    with patch("app.tasks.sync_playlist.ytdlp_service.get_playlist_info") as mock_ytdlp:
                        sync_youtube_playlist.apply(args=[sync.id])

        mock_api.assert_called_once_with("PLapi_task", "tok")
        mock_ytdlp.assert_not_called()

    def test_url_sync_task_calls_ytdlp_not_youtube_api(self, db):
        """URL sync task fetches via yt-dlp and never touches the YouTube API."""
        from app.tasks.sync_playlist import sync_youtube_playlist

        sync = _url_sync(db, "PLurl_task", dir_name="URL Playlist")
        fake_info = {"playlist_id": "PLurl_task", "playlist_title": "URL Playlist", "entries": []}

        with patch("app.database.SessionLocal", return_value=db):
            with patch("app.tasks.sync_playlist.ytdlp_service.get_playlist_info", return_value=fake_info) as mock_ytdlp:
                with patch("app.services.youtube_api_service.get_fresh_access_token") as mock_token:
                    sync_youtube_playlist.apply(args=[sync.id])

        mock_ytdlp.assert_called_once_with(sync.source_url)
        mock_token.assert_not_called()

    def test_api_sync_run_now_requires_oauth_token(self, client, db):
        """POST /run on an API sync returns 401 when no OAuth token is stored."""
        sync = _api_sync(db, "PLoauth_req")
        with patch("app.services.youtube_api_service.get_fresh_access_token", return_value=None):
            resp = client.post(f"/api/v1/youtube/syncs/{sync.id}/run")
        assert resp.status_code == 401

    def test_url_sync_run_now_skips_oauth_check(self, client, db):
        """POST /run on a URL sync works without any stored OAuth token."""
        sync = _url_sync(db, "PLoauth_skip")
        with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async") as mock_task:
            resp = client.post(f"/api/v1/youtube/syncs/{sync.id}/run")
        assert resp.status_code == 202
        mock_task.assert_called_once_with(args=[sync.id])

    def test_deleting_one_sync_does_not_affect_the_other(self, client, db):
        """Deleting an API sync leaves the URL sync intact."""
        api = _api_sync(db, "PLdel_api", audio_format="mp3")
        url = _url_sync(db, "PLdel_url", audio_format="mp4")

        client.delete(f"/api/v1/youtube/syncs/{api.id}")

        assert db.get(YoutubePlaylistSync, api.id) is None
        assert db.get(YoutubePlaylistSync, url.id) is not None

    def test_url_sync_response_contains_source_url_field(self, client, db):
        """URL sync response exposes source_url."""
        _url_sync(db, "PLsource_url",
                  source_url="https://www.youtube.com/playlist?list=PLsource_url")
        data = client.get("/api/v1/youtube/syncs").json()
        url_syncs = [s for s in data if s["source_type"] == "url"]
        assert len(url_syncs) == 1
        assert "PLsource_url" in url_syncs[0]["source_url"]

    def test_api_sync_response_has_empty_source_url(self, client, db):
        """API sync response has empty source_url."""
        _api_sync(db, "PLapi_no_url")
        data = client.get("/api/v1/youtube/syncs").json()
        api_syncs = [s for s in data if s["source_type"] == "api"]
        assert len(api_syncs) == 1
        assert api_syncs[0]["source_url"] == ""

    def test_api_and_url_syncs_have_independent_track_lists(self, client, db):
        """Tracks belong to a specific sync, not to a playlist_id."""
        api = _api_sync(db, "PLtracks_iso", audio_format="mp3")
        url = _url_sync(db, "PLtracks_iso", audio_format="mp4")
        _track(db, api, "vid1", status="complete", file_path="/tmp/a.mp3")

        resp_url = client.get(f"/api/v1/youtube/syncs/{url.id}/tracks")
        assert resp_url.json() == []

        resp_api = client.get(f"/api/v1/youtube/syncs/{api.id}/tracks")
        assert len(resp_api.json()) == 1

    def test_api_sync_and_url_sync_last_synced_are_independent(self, db):
        """Syncing one source type does not touch last_synced of the other."""
        from app.tasks.sync_playlist import sync_youtube_playlist

        api_sync = _api_sync(db, "PLlast_api", dir_name="Test Playlist")
        url_sync = _url_sync(db, "PLlast_url", dir_name="URL Playlist")
        assert api_sync.last_synced is None
        assert url_sync.last_synced is None

        fake_info = {"playlist_id": "PLlast_url", "playlist_title": "URL Playlist", "entries": []}
        with patch("app.database.SessionLocal", return_value=db):
            with patch("app.tasks.sync_playlist.ytdlp_service.get_playlist_info", return_value=fake_info):
                sync_youtube_playlist.apply(args=[url_sync.id])

        db.refresh(api_sync)
        db.refresh(url_sync)
        assert api_sync.last_synced is None  # not touched
        assert url_sync.last_synced is not None


# ── Feature 2: MP4 download ────────────────────────────────────────────────────

class TestMp4Download:
    """Verify yt-dlp options, metadata, and task integration for mp4/webm."""

    def _capture(self, audio_format, gain_percent=0.0, tmp_path=None):
        from app.services import ytdlp_service
        captured = {}

        def fake_ydl(opts):
            captured.update(opts)
            m = MagicMock()
            m.__enter__ = MagicMock(return_value=m)
            m.__exit__ = MagicMock(return_value=False)
            m.extract_info = MagicMock(return_value={
                "id": "vid1", "title": "Video Title", "uploader": "Channel", "duration": 300,
            })
            return m

        with patch("app.services.ytdlp_service.yt_dlp.YoutubeDL", side_effect=fake_ydl):
            meta = ytdlp_service.download_track(
                youtube_id="vid1",
                audio_format=audio_format,
                audio_quality="192",
                gain_percent=gain_percent,
                base_path=tmp_path,
            )
        return captured, meta

    # Format selector

    def test_mp4_format_selector_targets_mp4_container(self, tmp_path):
        opts, _ = self._capture("mp4", tmp_path=tmp_path)
        assert opts["format"].startswith("bestvideo[ext=mp4]+bestaudio")

    def test_mp4_format_selector_has_audio_fallback(self, tmp_path):
        opts, _ = self._capture("mp4", tmp_path=tmp_path)
        assert "bestvideo+bestaudio" in opts["format"]

    def test_webm_format_selector_targets_webm_container(self, tmp_path):
        opts, _ = self._capture("webm", tmp_path=tmp_path)
        assert opts["format"].startswith("bestvideo[ext=webm]+bestaudio")

    def test_mp4_sets_merge_output_format_to_mp4(self, tmp_path):
        opts, _ = self._capture("mp4", tmp_path=tmp_path)
        assert opts.get("merge_output_format") == "mp4"

    def test_webm_sets_merge_output_format_to_webm(self, tmp_path):
        opts, _ = self._capture("webm", tmp_path=tmp_path)
        assert opts.get("merge_output_format") == "webm"

    # Postprocessors

    def test_mp4_uses_ffmpeg_video_remuxer_postprocessor(self, tmp_path):
        opts, _ = self._capture("mp4", tmp_path=tmp_path)
        pps = opts["postprocessors"]
        assert any(pp["key"] == "FFmpegVideoRemuxer" for pp in pps)

    def test_mp4_remuxer_requests_mp4_container(self, tmp_path):
        opts, _ = self._capture("mp4", tmp_path=tmp_path)
        pps = opts["postprocessors"]
        remuxer = next(pp for pp in pps if pp["key"] == "FFmpegVideoRemuxer")
        assert remuxer.get("preferedformat") == "mp4"

    def test_webm_uses_ffmpeg_video_remuxer_postprocessor(self, tmp_path):
        opts, _ = self._capture("webm", tmp_path=tmp_path)
        pps = opts["postprocessors"]
        assert any(pp["key"] == "FFmpegVideoRemuxer" and pp.get("preferedformat") == "webm" for pp in pps)

    def test_mp4_does_not_use_audio_extract_postprocessor(self, tmp_path):
        opts, _ = self._capture("mp4", tmp_path=tmp_path)
        pps = opts["postprocessors"]
        assert not any(pp["key"] == "FFmpegExtractAudio" for pp in pps)

    # Gain suppression

    def test_mp4_gain_not_applied_when_nonzero(self, tmp_path):
        opts, _ = self._capture("mp4", gain_percent=50.0, tmp_path=tmp_path)
        args = opts.get("postprocessor_args", [])
        assert "-af" not in args

    def test_webm_gain_not_applied_when_nonzero(self, tmp_path):
        opts, _ = self._capture("webm", gain_percent=20.0, tmp_path=tmp_path)
        args = opts.get("postprocessor_args", [])
        assert "-af" not in args

    def test_mp3_gain_is_applied(self, tmp_path):
        opts, _ = self._capture("mp3", gain_percent=10.0, tmp_path=tmp_path)
        assert "-af" in opts.get("postprocessor_args", [])

    # Metadata

    def test_mp4_metadata_file_format_is_mp4(self, tmp_path):
        _, meta = self._capture("mp4", tmp_path=tmp_path)
        assert meta["file_format"] == "mp4"

    def test_mp4_metadata_file_path_ends_with_mp4(self, tmp_path):
        _, meta = self._capture("mp4", tmp_path=tmp_path)
        assert meta["file_path"].endswith(".mp4")

    def test_webm_metadata_file_format_is_webm(self, tmp_path):
        _, meta = self._capture("webm", tmp_path=tmp_path)
        assert meta["file_format"] == "webm"

    def test_webm_metadata_file_path_ends_with_webm(self, tmp_path):
        _, meta = self._capture("webm", tmp_path=tmp_path)
        assert meta["file_path"].endswith(".webm")

    # Task-level integration

    def test_download_task_passes_mp4_format_to_ytdlp_service(self, db, tmp_path):
        """download_playlist_sync_track calls ytdlp_service with audio_format='mp4'."""
        from app.tasks.sync_playlist import download_playlist_sync_track

        sync = YoutubePlaylistSync(
            playlist_id="PLtask_mp4",
            playlist_name="Task MP4",
            audio_format="mp4",
            audio_quality="192",
            dir_name="Task MP4",
            enabled=True,
        )
        db.add(sync)
        db.commit()
        db.refresh(sync)
        track = _track(db, sync, "mp4task_vid")

        fake_meta = {
            "youtube_id": "mp4task_vid", "title": "MP4 Task", "artist": "Ch",
            "duration_secs": 120, "file_path": "/tmp/x.mp4", "file_format": "mp4",
            "file_size_bytes": 1000, "thumbnail_path": None,
        }
        with patch("app.database.SessionLocal", return_value=db):
            with patch("app.tasks.sync_playlist.settings.downloads_path", tmp_path):
                with patch("app.tasks.sync_playlist.ytdlp_service.download_track", return_value=fake_meta) as mock_dl:
                    with patch("app.tasks.sync_playlist._redis.delete"):
                        download_playlist_sync_track.apply(args=[track.id])

        _, kwargs = mock_dl.call_args
        assert kwargs["audio_format"] == "mp4"
        db.refresh(track)
        assert track.status == "complete"
        assert track.file_format == "mp4"

    def test_download_task_passes_webm_format_to_ytdlp_service(self, db, tmp_path):
        """download_playlist_sync_track calls ytdlp_service with audio_format='webm'."""
        from app.tasks.sync_playlist import download_playlist_sync_track

        sync = YoutubePlaylistSync(
            playlist_id="PLtask_webm",
            playlist_name="Task WebM",
            audio_format="webm",
            audio_quality="192",
            dir_name="Task WebM",
            enabled=True,
        )
        db.add(sync)
        db.commit()
        db.refresh(sync)
        track = _track(db, sync, "webm_vid")

        fake_meta = {
            "youtube_id": "webm_vid", "title": "WebM Track", "artist": "Ch",
            "duration_secs": 90, "file_path": "/tmp/x.webm", "file_format": "webm",
            "file_size_bytes": 500, "thumbnail_path": None,
        }
        with patch("app.database.SessionLocal", return_value=db):
            with patch("app.tasks.sync_playlist.settings.downloads_path", tmp_path):
                with patch("app.tasks.sync_playlist.ytdlp_service.download_track", return_value=fake_meta) as mock_dl:
                    with patch("app.tasks.sync_playlist._redis.delete"):
                        download_playlist_sync_track.apply(args=[track.id])

        _, kwargs = mock_dl.call_args
        assert kwargs["audio_format"] == "webm"
        db.refresh(track)
        assert track.status == "complete"
        assert track.file_format == "webm"

    def test_create_sync_with_webm_accepted(self, client):
        with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async"):
            resp = client.post("/api/v1/youtube/syncs", json={
                "playlist_id": "PLwebm",
                "playlist_name": "WebM Vids",
                "audio_format": "webm",
            })
        assert resp.status_code == 201
        assert resp.json()["audio_format"] == "webm"

    def test_is_video_format_recognizes_mp4_and_webm(self):
        from app.services.ytdlp_service import is_video_format
        assert is_video_format("mp4") is True
        assert is_video_format("webm") is True

    def test_is_video_format_rejects_audio_formats(self):
        from app.services.ytdlp_service import is_video_format
        for fmt in ("mp3", "flac", "aac", "ogg", "m4a"):
            assert is_video_format(fmt) is False, f"{fmt} should not be a video format"

    def test_audio_format_has_no_merge_output_format_option(self, tmp_path):
        opts, _ = self._capture("mp3", tmp_path=tmp_path)
        assert "merge_output_format" not in opts


# ── Feature 3: Multiple format specification ───────────────────────────────────

class TestMultipleFormatSpecification:
    """Verify that one playlist can be synced in any number of distinct formats."""

    def test_schema_accepts_all_seven_valid_formats(self):
        from app.schemas import YoutubePlaylistSyncCreate
        for fmt in ("mp3", "flac", "aac", "ogg", "m4a", "mp4", "webm"):
            obj = YoutubePlaylistSyncCreate(playlist_id="PL1", playlist_name="T", audio_format=fmt)
            assert obj.audio_format == fmt, f"Schema rejected valid format: {fmt}"

    def test_schema_rejects_invalid_format(self):
        import pydantic
        from app.schemas import YoutubePlaylistSyncCreate
        with pytest.raises(pydantic.ValidationError):
            YoutubePlaylistSyncCreate(playlist_id="PL1", playlist_name="T", audio_format="avi")

    def test_same_playlist_three_different_formats_all_created(self, client, db):
        for fmt in ("mp3", "mp4", "flac"):
            with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async"):
                resp = client.post("/api/v1/youtube/syncs", json={
                    "playlist_id": "PLthree",
                    "playlist_name": "Triple Format",
                    "audio_format": fmt,
                })
            assert resp.status_code == 201, f"Format {fmt} failed: {resp.json()}"

        assert db.query(YoutubePlaylistSync).filter_by(playlist_id="PLthree").count() == 3

    def test_same_playlist_all_seven_formats_all_created(self, client, db):
        for fmt in ("mp3", "flac", "aac", "ogg", "m4a", "mp4", "webm"):
            with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async"):
                resp = client.post("/api/v1/youtube/syncs", json={
                    "playlist_id": "PLall7",
                    "playlist_name": "All Formats",
                    "audio_format": fmt,
                })
            assert resp.status_code == 201, f"Format {fmt} rejected: {resp.json()}"

        assert db.query(YoutubePlaylistSync).filter_by(playlist_id="PLall7").count() == 7

    def test_duplicate_format_for_same_playlist_rejected_with_409(self, client, db):
        with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async"):
            client.post("/api/v1/youtube/syncs", json={
                "playlist_id": "PLdup", "playlist_name": "Dup", "audio_format": "mp3",
            })
        with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async"):
            resp = client.post("/api/v1/youtube/syncs", json={
                "playlist_id": "PLdup", "playlist_name": "Dup", "audio_format": "mp3",
            })
        assert resp.status_code == 409

    def test_each_format_sync_listed_separately_in_get_syncs(self, client, db):
        for fmt in ("mp3", "flac", "mp4"):
            s = YoutubePlaylistSync(
                playlist_id="PLlisted",
                playlist_name="Listed",
                audio_format=fmt,
                audio_quality="192",
                enabled=True,
            )
            db.add(s)
        db.commit()

        data = client.get("/api/v1/youtube/syncs").json()
        formats = {s["audio_format"] for s in data}
        assert {"mp3", "flac", "mp4"} == formats

    def test_tracks_belong_to_format_not_to_playlist_id(self, client, db):
        """Adding a track to mp3 sync does not appear in mp4 sync for same playlist."""
        mp3 = YoutubePlaylistSync(
            playlist_id="PLiso", playlist_name="Iso", audio_format="mp3",
            audio_quality="192", enabled=True,
        )
        mp4 = YoutubePlaylistSync(
            playlist_id="PLiso", playlist_name="Iso", audio_format="mp4",
            audio_quality="192", enabled=True,
        )
        db.add(mp3)
        db.add(mp4)
        db.commit()
        _track(db, mp3, "iso_vid", status="complete", file_path="/tmp/iso.mp3")

        assert client.get(f"/api/v1/youtube/syncs/{mp4.id}/tracks").json() == []
        assert len(client.get(f"/api/v1/youtube/syncs/{mp3.id}/tracks").json()) == 1

    def test_sync_task_only_downloads_tracks_for_its_own_format(self, db):
        """Running the mp3 sync does not create tracks under the mp4 sync."""
        from app.tasks.sync_playlist import sync_youtube_playlist

        mp3 = YoutubePlaylistSync(
            playlist_id="PLownfmt", playlist_name="Own Format", audio_format="mp3",
            audio_quality="192", dir_name="Own Format [mp3]", enabled=True,
        )
        mp4 = YoutubePlaylistSync(
            playlist_id="PLownfmt", playlist_name="Own Format", audio_format="mp4",
            audio_quality="192", dir_name="Own Format [mp4]", enabled=True,
        )
        db.add(mp3)
        db.add(mp4)
        db.commit()

        remote = [{"youtube_id": "v1", "title": "Song", "position": 1, "thumbnail_url": None}]
        with patch("app.database.SessionLocal", return_value=db):
            with patch("app.services.youtube_api_service.get_fresh_access_token", return_value="tok"):
                with patch("app.services.youtube_api_service.get_playlist_items", return_value=remote):
                    with patch("app.tasks.sync_playlist.download_playlist_sync_track.apply_async"):
                        sync_youtube_playlist.apply(args=[mp3.id])

        assert db.query(PlaylistSyncTrack).filter_by(playlist_sync_id=mp3.id).count() == 1
        assert db.query(PlaylistSyncTrack).filter_by(playlist_sync_id=mp4.id).count() == 0

    def test_deleting_one_format_sync_leaves_other_format_intact(self, client, db):
        mp3 = YoutubePlaylistSync(
            playlist_id="PLdelfmt", playlist_name="Del Format",
            audio_format="mp3", audio_quality="192", enabled=True,
        )
        mp4 = YoutubePlaylistSync(
            playlist_id="PLdelfmt", playlist_name="Del Format",
            audio_format="mp4", audio_quality="192", enabled=True,
        )
        db.add(mp3)
        db.add(mp4)
        db.commit()

        client.delete(f"/api/v1/youtube/syncs/{mp3.id}")

        assert db.get(YoutubePlaylistSync, mp3.id) is None
        assert db.get(YoutubePlaylistSync, mp4.id) is not None

    def test_updating_format_from_mp3_to_flac_succeeds(self, client, db):
        sync = YoutubePlaylistSync(
            playlist_id="PLupdfmt", playlist_name="Update Fmt",
            audio_format="mp3", audio_quality="192", dir_name="Update Fmt", enabled=True,
        )
        db.add(sync)
        db.commit()

        resp = client.patch(f"/api/v1/youtube/syncs/{sync.id}", json={"audio_format": "flac"})
        assert resp.status_code == 200
        assert resp.json()["audio_format"] == "flac"

    def test_updating_to_existing_format_returns_409(self, client, db):
        mp3 = YoutubePlaylistSync(
            playlist_id="PLconf", playlist_name="Conflict",
            audio_format="mp3", audio_quality="192", enabled=True,
        )
        mp4 = YoutubePlaylistSync(
            playlist_id="PLconf", playlist_name="Conflict",
            audio_format="mp4", audio_quality="192", enabled=True,
        )
        db.add(mp3)
        db.add(mp4)
        db.commit()

        resp = client.patch(f"/api/v1/youtube/syncs/{mp4.id}", json={"audio_format": "mp3"})
        assert resp.status_code == 409


# ── Feature 4: Folder naming for multiple formats ──────────────────────────────

class TestFolderNamingMultipleFormats:
    """Verify directory naming rules when the same playlist is synced in multiple formats."""

    def test_sole_sync_gets_plain_dir_name(self, client, db):
        with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async"):
            client.post("/api/v1/youtube/syncs", json={
                "playlist_id": "PLplain",
                "playlist_name": "Plain Dir",
                "audio_format": "mp3",
            })
        sync = db.query(YoutubePlaylistSync).filter_by(playlist_id="PLplain").first()
        assert sync.dir_name == "Plain Dir"

    def test_second_format_causes_both_syncs_to_get_suffixed_dir_names(self, client, db):
        with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async"):
            client.post("/api/v1/youtube/syncs", json={
                "playlist_id": "PLsufx", "playlist_name": "Shared Name", "audio_format": "mp3",
            })
            client.post("/api/v1/youtube/syncs", json={
                "playlist_id": "PLsufx", "playlist_name": "Shared Name", "audio_format": "mp4",
            })

        dirs = {
            s.audio_format: s.dir_name
            for s in db.query(YoutubePlaylistSync).filter_by(playlist_id="PLsufx").all()
        }
        assert dirs == {"mp3": "Shared Name [mp3]", "mp4": "Shared Name [mp4]"}

    def test_three_formats_same_playlist_all_suffixed_correctly(self, client, db):
        for fmt in ("mp3", "mp4", "flac"):
            with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async"):
                client.post("/api/v1/youtube/syncs", json={
                    "playlist_id": "PLtrip", "playlist_name": "Triple", "audio_format": fmt,
                })

        dirs = {
            s.audio_format: s.dir_name
            for s in db.query(YoutubePlaylistSync).filter_by(playlist_id="PLtrip").all()
        }
        assert dirs["mp3"] == "Triple [mp3]"
        assert dirs["mp4"] == "Triple [mp4]"
        assert dirs["flac"] == "Triple [flac]"

    def test_all_seven_formats_have_unique_dir_names(self, client, db):
        all_fmts = ("mp3", "flac", "aac", "ogg", "m4a", "mp4", "webm")
        for fmt in all_fmts:
            with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async"):
                client.post("/api/v1/youtube/syncs", json={
                    "playlist_id": "PLuniq7", "playlist_name": "Unique7", "audio_format": fmt,
                })

        syncs = db.query(YoutubePlaylistSync).filter_by(playlist_id="PLuniq7").all()
        dir_names = [s.dir_name for s in syncs]
        assert len(dir_names) == len(set(dir_names)), f"Duplicate dir_names: {dir_names}"

    def test_dir_name_suffix_exactly_matches_audio_format_string(self, client, db):
        """dir_name ends with [<audio_format>] for each sync after collision."""
        for fmt in ("mp3", "mp4", "webm"):
            with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async"):
                client.post("/api/v1/youtube/syncs", json={
                    "playlist_id": "PLexact", "playlist_name": "Exact", "audio_format": fmt,
                })

        for sync in db.query(YoutubePlaylistSync).filter_by(playlist_id="PLexact").all():
            assert sync.dir_name == f"Exact [{sync.audio_format}]", (
                f"Expected 'Exact [{sync.audio_format}]', got '{sync.dir_name}'"
            )

    def test_japanese_playlist_name_gets_format_suffix(self, client, db):
        for fmt in ("mp3", "mp4"):
            with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async"):
                client.post("/api/v1/youtube/syncs", json={
                    "playlist_id": "PLjp", "playlist_name": "作業用BGM", "audio_format": fmt,
                })

        dirs = {
            s.audio_format: s.dir_name
            for s in db.query(YoutubePlaylistSync).filter_by(playlist_id="PLjp").all()
        }
        assert dirs["mp3"] == "作業用BGM [mp3]"
        assert dirs["mp4"] == "作業用BGM [mp4]"

    def test_mp4_sync_dir_ends_with_mp4_bracket(self, client, db):
        for fmt in ("mp3", "mp4"):
            with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async"):
                client.post("/api/v1/youtube/syncs", json={
                    "playlist_id": "PLvd", "playlist_name": "Video Dir", "audio_format": fmt,
                })

        mp4 = db.query(YoutubePlaylistSync).filter_by(playlist_id="PLvd", audio_format="mp4").first()
        assert mp4.dir_name == "Video Dir [mp4]"

    def test_webm_sync_dir_ends_with_webm_bracket(self, client, db):
        for fmt in ("mp3", "webm"):
            with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async"):
                client.post("/api/v1/youtube/syncs", json={
                    "playlist_id": "PLwd", "playlist_name": "WebM Dir", "audio_format": fmt,
                })

        webm = db.query(YoutubePlaylistSync).filter_by(playlist_id="PLwd", audio_format="webm").first()
        assert webm.dir_name == "WebM Dir [webm]"

    def test_dir_name_unchanged_when_updating_non_format_field(self, client, db):
        with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async"):
            client.post("/api/v1/youtube/syncs", json={
                "playlist_id": "PLstable", "playlist_name": "Stable", "audio_format": "mp3",
            })
        sync = db.query(YoutubePlaylistSync).filter_by(playlist_id="PLstable").first()
        original = sync.dir_name

        client.patch(f"/api/v1/youtube/syncs/{sync.id}", json={"enabled": False, "audio_quality": "320"})
        db.refresh(sync)
        assert sync.dir_name == original

    def test_download_task_uses_dir_name_as_base_path_for_mp4(self, db, tmp_path):
        """Download task resolves base_path from sync.dir_name for mp4."""
        from app.tasks.sync_playlist import download_playlist_sync_track

        sync = YoutubePlaylistSync(
            playlist_id="PLbasepath",
            playlist_name="Base Path",
            audio_format="mp4",
            audio_quality="192",
            dir_name="Base Path [mp4]",
            enabled=True,
        )
        db.add(sync)
        db.commit()
        db.refresh(sync)
        track = _track(db, sync, "vid_basepath")

        fake_meta = {
            "youtube_id": "vid_basepath", "title": "T", "artist": None, "duration_secs": 1,
            "file_path": "/tmp/x.mp4", "file_format": "mp4", "file_size_bytes": 1, "thumbnail_path": None,
        }
        with patch("app.database.SessionLocal", return_value=db):
            with patch("app.tasks.sync_playlist.settings.downloads_path", tmp_path):
                with patch("app.tasks.sync_playlist.ytdlp_service.download_track", return_value=fake_meta) as mock_dl:
                    with patch("app.tasks.sync_playlist._redis.delete"):
                        download_playlist_sync_track.apply(args=[track.id])

        _, kwargs = mock_dl.call_args
        assert kwargs["base_path"] == tmp_path / "Base Path [mp4]"

    def test_folder_rename_on_disk_when_second_format_added(self, client, db, tmp_path):
        """The original folder is renamed on disk when a second format forces suffixes."""
        plain_dir = tmp_path / "Renamed"
        plain_dir.mkdir()
        (plain_dir / "song.mp3").write_bytes(b"data")

        with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async"):
            client.post("/api/v1/youtube/syncs", json={
                "playlist_id": "PLren", "playlist_name": "Renamed", "audio_format": "mp3",
            })

        first = db.query(YoutubePlaylistSync).filter_by(playlist_id="PLren", audio_format="mp3").first()
        t = _track(db, first, "ren_v1", file_path=str(plain_dir / "song.mp3"))

        with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async"):
            with patch("app.services.sync_dirs.settings.downloads_path", tmp_path):
                client.post("/api/v1/youtube/syncs", json={
                    "playlist_id": "PLren", "playlist_name": "Renamed", "audio_format": "mp4",
                })

        db.refresh(first)
        assert first.dir_name == "Renamed [mp3]"
        assert not plain_dir.exists()
        assert (tmp_path / "Renamed [mp3]" / "song.mp3").exists()

        db.refresh(t)
        assert t.file_path == str(tmp_path / "Renamed [mp3]" / "song.mp3")

    def test_allocate_dir_name_for_mp4_with_existing_mp3(self, db):
        """allocate_sync_dir_name returns '[mp4]' suffix when mp3 already exists."""
        from app.services.sync_dirs import allocate_sync_dir_name

        s = YoutubePlaylistSync(
            playlist_id="PLalloc", playlist_name="Alloc", audio_format="mp3",
            audio_quality="192", dir_name="Alloc", enabled=True,
        )
        db.add(s)
        db.commit()

        result = allocate_sync_dir_name(db, "Alloc", "mp4")
        assert result == "Alloc [mp4]"

    def test_allocate_dir_name_for_webm_with_existing_mp3_and_mp4(self, db):
        """allocate_sync_dir_name returns '[webm]' suffix when mp3 and mp4 already exist."""
        from app.services.sync_dirs import allocate_sync_dir_name

        for fmt, dn in [("mp3", "Alloc3 [mp3]"), ("mp4", "Alloc3 [mp4]")]:
            db.add(YoutubePlaylistSync(
                playlist_id="PLalloc3", playlist_name="Alloc3", audio_format=fmt,
                audio_quality="192", dir_name=dn, enabled=True,
            ))
        db.commit()

        result = allocate_sync_dir_name(db, "Alloc3", "webm")
        assert result == "Alloc3 [webm]"
