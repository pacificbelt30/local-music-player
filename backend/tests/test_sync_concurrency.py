"""Concurrent workers, pause and deletion must not publish duplicate/stale files."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.models import AppSetting, PlaylistSyncTrack, YoutubePlaylistSync
from app.tasks.sync_playlist import sync_youtube_playlist, download_playlist_sync_track


@pytest.fixture
def operation(db, tmp_path):
    sync = YoutubePlaylistSync(
        playlist_id="race",
        playlist_name="Race",
        dir_name="Race",
        source_type="url",
        source_url="https://www.youtube.com/playlist?list=race",
    )
    db.add(sync)
    db.commit()
    track = PlaylistSyncTrack(
        playlist_sync_id=sync.id,
        youtube_id="race-video",
        title="Race track",
        status="pending",
        celery_task_id="unit-attempt",
    )
    db.add(track)
    db.commit()
    # Keep the fixture session open while exercising nested task invocations.
    with (
        patch("app.tasks.sync_playlist.SessionLocal", return_value=db),
        patch.object(db, "close"),
        patch("app.tasks.sync_playlist.settings.downloads_path", tmp_path),
        patch("app.tasks.sync_playlist.notify"),
        patch("app.tasks.sync_playlist._redis.delete"),
    ):
        yield sync, track


def locking_client():
    held = set()

    def create(key, **kwargs):
        lock = MagicMock()

        def acquire(**kwargs):
            if key in held:
                return False
            held.add(key)
            return True

        lock.acquire.side_effect = acquire
        lock.release.side_effect = lambda: held.remove(key)
        return lock

    return create


def test_parallel_sync_skips_remote_fetch_and_dispatch(operation, db):
    sync, _ = operation

    def remote(url):
        sync_youtube_playlist.run(sync.id)
        return {"entries": []}

    with (
        patch("app.tasks.sync_playlist._redis.lock", side_effect=locking_client()),
        patch(
            "app.tasks.sync_playlist.ytdlp_service.get_playlist_info",
            side_effect=remote,
        ) as fetch,
    ):
        sync_youtube_playlist.run(sync.id)
    assert fetch.call_count == 1


def test_parallel_track_download_happens_once(operation, db):
    sync, track = operation

    def download(**kwargs):
        download_playlist_sync_track.run(track.id)
        path = kwargs["base_path"] / "race.mp3"
        path.write_bytes(b"audio")
        return {"title": "Race", "file_path": str(path)}

    with (
        patch("app.tasks.sync_playlist._redis.lock", side_effect=locking_client()),
        patch(
            "app.tasks.sync_playlist.ytdlp_service.download_track", side_effect=download
        ) as fetch,
    ):
        download_playlist_sync_track.run(track.id)
    assert fetch.call_count == 1
    assert track.status == "complete"
    assert Path(track.file_path).read_bytes() == b"audio"
    assert not Path(track.file_path).parent.joinpath(".lmp-").exists()


@pytest.mark.parametrize("manual", [False, True])
def test_queued_download_respects_pause_except_manual_run(operation, db, manual):
    sync, track = operation
    sync.enabled = False
    db.commit()
    with patch(
        "app.tasks.sync_playlist.ytdlp_service.download_track",
        return_value={"title": "Race", "file_path": "/not-a-real-file"},
    ) as fetch:
        download_playlist_sync_track.run(track.id, manual=manual)
    assert fetch.call_count == int(manual)
    assert track.status == ("complete" if manual else "pending")
    if not manual:
        assert track.celery_task_id is None


@pytest.mark.parametrize("action", ["pause", "delete"])
def test_sync_rechecks_state_after_remote_fetch(operation, db, action):
    sync, track = operation
    sync_id = sync.id

    def remote(url):
        if action == "pause":
            sync.enabled = False
        else:
            db.delete(sync)
        db.commit()
        return {"entries": [{"youtube_id": "new", "title": "New", "position": 0}]}

    with (
        patch(
            "app.tasks.sync_playlist.ytdlp_service.get_playlist_info",
            side_effect=remote,
        ),
        patch(
            "app.tasks.sync_playlist.download_playlist_sync_track.apply_async"
        ) as dispatch,
    ):
        sync_youtube_playlist.run(sync_id)
    dispatch.assert_not_called()


@pytest.mark.parametrize("keep", [False, True])
def test_deletion_while_downloading_obeys_file_choice(operation, db, keep):
    sync, track = operation
    track_id = track.id
    output = []

    def download(**kwargs):
        path = kwargs["base_path"] / "race.mp3"
        path.write_bytes(b"audio")
        output.append(path.parent.parent / "race.mp3")
        db.merge(
            AppSetting(
                key="deleted-download:unit-attempt", value="keep" if keep else "files"
            )
        )
        db.delete(sync)
        db.commit()
        return {"title": "Race", "file_path": str(path)}

    with (
        patch(
            "app.tasks.sync_playlist.ytdlp_service.download_track", side_effect=download
        ),
        patch(
            "app.tasks.sync_playlist._redis.get",
            return_value="keep" if keep else "files",
        ),
    ):
        download_playlist_sync_track.run(track_id)
    assert db.get(PlaylistSyncTrack, track_id) is None
    assert output[0].exists() == keep
    assert list(output[0].parent.glob(".lmp-*")) == []


def test_normal_sync_requeues_download_after_dead_worker_lease_expires(operation, db):
    sync, track = operation
    track.status = "downloading"
    track.celery_task_id = "dead-worker"
    db.commit()
    remote = {
        "entries": [{"youtube_id": track.youtube_id, "title": "Race", "position": 0}]
    }
    with (
        patch("app.tasks.sync_playlist._redis.exists", return_value=False),
        patch(
            "app.tasks.sync_playlist.ytdlp_service.get_playlist_info",
            return_value=remote,
        ),
        patch(
            "app.tasks.sync_playlist.download_playlist_sync_track.apply_async"
        ) as dispatch,
    ):
        sync_youtube_playlist.run(sync.id)
    assert dispatch.call_count == 1
    assert track.status == "pending" and track.celery_task_id != "dead-worker"


def test_enqueue_cannot_replace_the_identity_of_a_running_download(operation, db):
    from app.tasks.sync_playlist import enqueue_playlist_track

    sync, track = operation
    track.status = "downloading"
    track.celery_task_id = "active"
    db.commit()
    with patch(
        "app.tasks.sync_playlist.download_playlist_sync_track.apply_async"
    ) as dispatch:
        enqueue_playlist_track(db, track, manual=True)
    db.refresh(track)
    assert track.celery_task_id == "active" and track.status == "downloading"
    dispatch.assert_not_called()


def test_obsolete_queued_task_cannot_claim_a_newer_request(operation, db):
    sync, track = operation
    track.celery_task_id = "new-request"
    db.commit()
    with patch("app.tasks.sync_playlist.ytdlp_service.download_track") as download:
        download_playlist_sync_track.apply(
            args=[track.id], task_id="obsolete-request", throw=True
        )
    download.assert_not_called()
    db.refresh(track)
    assert track.celery_task_id == "new-request"
