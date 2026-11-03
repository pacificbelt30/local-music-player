"""Regression coverage for manual sync and playlist attempt lifetimes."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest

from app.api.youtube_playlists import _mark_stuck_playlist_tracks_failed
from app.models import PlaylistSyncTrack, YoutubePlaylistSync
from app.tasks.sync_playlist import sync_youtube_playlist, download_playlist_sync_track, enqueue_playlist_track


def make_sync(db, enabled=True):
    sync = YoutubePlaylistSync(playlist_id="attempts", playlist_name="Attempts", enabled=enabled,
                               source_type="url", source_url="https://www.youtube.com/playlist?list=attempts")
    db.add(sync)
    db.commit()
    return sync


def make_track(db, **fields):
    sync = make_sync(db)
    values = dict(playlist_sync_id=sync.id, youtube_id="attempt", title="Attempt", status="downloading",
                  added_at=datetime.now(timezone.utc)-timedelta(hours=5),
                  started_at=datetime.now(timezone.utc)-timedelta(minutes=1), celery_task_id="live-task")
    values.update(fields)
    track = PlaylistSyncTrack(**values)
    db.add(track)
    db.commit()
    return track


def test_manual_run_executes_paused_sync_without_enabling_automatic_sync(client, db):
    sync = make_sync(db, enabled=False)
    sync_id = sync.id
    with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async") as dispatch:
        response = client.post(f"/api/v1/youtube/syncs/{sync.id}/run")
    assert response.status_code == 202
    args, kwargs = dispatch.call_args.args, dispatch.call_args.kwargs
    with patch("app.tasks.sync_playlist.SessionLocal", return_value=db), \
         patch("app.tasks.sync_playlist.ytdlp_service.get_playlist_info", return_value={"entries": []}) as remote:
        sync_youtube_playlist.apply(*args, **kwargs, throw=True)
    remote.assert_called_once()
    sync = db.get(YoutubePlaylistSync, sync_id)
    assert sync.last_synced is not None
    assert sync.enabled is False


def test_automatic_task_still_skips_paused_sync(db):
    sync = make_sync(db, enabled=False)
    with patch("app.tasks.sync_playlist.SessionLocal", return_value=db), \
         patch("app.tasks.sync_playlist.ytdlp_service.get_playlist_info") as remote:
        sync_youtube_playlist.apply(args=[sync.id], throw=True)
    remote.assert_not_called()


def test_long_wait_before_start_does_not_count_as_download_duration(db):
    track = make_track(db)
    with patch("app.tasks.celery_app.celery_app.AsyncResult") as result:
        _mark_stuck_playlist_tracks_failed(db, track.playlist_sync_id)
    result.assert_not_called()
    assert track.status == "downloading"


def test_legacy_download_without_start_time_is_not_failed_from_discovery_time(db):
    track = make_track(db, started_at=None, celery_task_id=None)
    _mark_stuck_playlist_tracks_failed(db, track.playlist_sync_id)
    assert track.status == "downloading"


@pytest.mark.parametrize("progress,active", [("0", None), (None, {"worker": [{"id": "live-task"}]}), (None, None)])
def test_fresh_progress_active_conversion_or_missing_worker_reply_is_not_a_crash(db, progress, active):
    track = make_track(db, started_at=datetime.now(timezone.utc)-timedelta(hours=3))
    with patch("app.tasks.celery_app.celery_app.AsyncResult") as result, \
         patch("app.tasks.sync_playlist._redis.get", return_value=progress), \
         patch("app.tasks.celery_app.celery_app.control.inspect") as inspect:
        result.return_value.state = "STARTED"
        inspect.return_value.active.return_value = active
        _mark_stuck_playlist_tracks_failed(db, track.playlist_sync_id)
    assert track.status == "downloading"


def test_lost_download_recovers_after_worker_restart(db):
    track = make_track(db, started_at=datetime.now(timezone.utc)-timedelta(hours=3))
    with patch("app.tasks.celery_app.celery_app.AsyncResult") as result, \
         patch("app.tasks.sync_playlist._redis.get", return_value=None), \
         patch("app.tasks.celery_app.celery_app.control.inspect") as inspect:
        result.return_value.state = "PENDING"
        inspect.return_value.active.return_value = {"restarted-worker": []}
        _mark_stuck_playlist_tracks_failed(db, track.playlist_sync_id)
    assert track.status == "failed"


@pytest.mark.parametrize("status", ["pending", "downloading"])
def test_terminal_task_is_failed_but_a_queued_task_is_not(db, status):
    track = make_track(db, status=status, started_at=datetime.now(timezone.utc)-timedelta(hours=3))
    with patch("app.tasks.celery_app.celery_app.AsyncResult") as result:
        result.return_value.state = "PENDING"
        if status == "pending":
            _mark_stuck_playlist_tracks_failed(db, track.playlist_sync_id)
        assert track.status == status
        result.return_value.state = "FAILURE"
        _mark_stuck_playlist_tracks_failed(db, track.playlist_sync_id)
    assert track.status == "failed"


def test_enqueue_persists_new_attempt_before_dispatch(db):
    track = make_track(db, status="pending")
    def dispatch(*, args, task_id):
        db.refresh(track)
        assert args == [track.id]
        assert task_id == track.celery_task_id
        assert track.started_at is None
        assert (datetime.now(timezone.utc)-track.added_at.replace(tzinfo=timezone.utc)).total_seconds() < 10
    with patch("app.tasks.sync_playlist.download_playlist_sync_track.apply_async", side_effect=dispatch):
        enqueue_playlist_track(db, track)


def test_dispatch_failure_is_visible_and_retryable(db):
    track = make_track(db, status="pending")
    with patch("app.tasks.sync_playlist.download_playlist_sync_track.apply_async", side_effect=ConnectionError("broker offline")):
        with pytest.raises(ConnectionError):
            enqueue_playlist_track(db, track)
    assert track.status == "failed"
    assert "broker offline" in track.error_message


def test_worker_persists_actual_start_and_task_id(db, tmp_path):
    track = make_track(db, status="pending", started_at=None, celery_task_id="actual-attempt")
    track_id = track.id
    def download(**kwargs):
        db.refresh(track)
        assert track.status == "downloading"
        assert track.started_at is not None
        assert (datetime.now(timezone.utc)-track.started_at.replace(tzinfo=timezone.utc)).total_seconds() < 10
        assert track.celery_task_id == "actual-attempt"
        return {"title": "Downloaded", "file_path": str(tmp_path/"song.mp3")}
    with patch("app.tasks.sync_playlist.SessionLocal", return_value=db), \
         patch("app.tasks.sync_playlist.settings.downloads_path", tmp_path), \
         patch("app.tasks.sync_playlist._redis", MagicMock()), \
         patch("app.tasks.sync_playlist.notify"), \
         patch("app.tasks.sync_playlist.ytdlp_service.download_track", side_effect=download):
        download_playlist_sync_track.apply(args=[track.id], task_id="actual-attempt", throw=True)
    track = db.get(PlaylistSyncTrack, track_id)
    assert track.status == "complete"
