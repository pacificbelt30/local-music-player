"""Regression test: a playlist containing the same video twice must not crash
the sync with a UNIQUE(playlist_sync_id, youtube_id) constraint violation."""
from unittest.mock import patch

from app.models import PlaylistSyncTrack, YoutubePlaylistSync


def _make_url_sync(db):
    sync = YoutubePlaylistSync(
        playlist_id="PLdup", playlist_name="Dup Mix",
        audio_format="mp3", audio_quality="192", dir_name="Dup Mix",
        source_type="url", source_url="https://example.com/playlist",
    )
    db.add(sync)
    db.commit()
    db.refresh(sync)
    return sync


def test_sync_handles_duplicate_youtube_id_in_playlist(db):
    from app.tasks.sync_playlist import sync_youtube_playlist

    sync = _make_url_sync(db)

    # Same youtube_id appears twice in the remote playlist
    remote_info = {
        "entries": [
            {"youtube_id": "vid_aaa", "title": "Song A", "position": 0},
            {"youtube_id": "vid_bbb", "title": "Song B", "position": 1},
            {"youtube_id": "vid_aaa", "title": "Song A", "position": 2},
        ]
    }

    with patch("app.database.SessionLocal", return_value=db):
        with patch("app.services.ytdlp_service.get_playlist_info", return_value=remote_info):
            with patch("app.tasks.sync_playlist.download_playlist_sync_track.apply_async") as mock_dl:
                # Must not raise IntegrityError
                sync_youtube_playlist.apply(args=[sync.id])

    tracks = db.query(PlaylistSyncTrack).filter_by(playlist_sync_id=sync.id).all()
    youtube_ids = sorted(t.youtube_id for t in tracks)
    # Only one row per youtube_id despite the duplicate in the playlist
    assert youtube_ids == ["vid_aaa", "vid_bbb"]
    # Each unique track dispatched exactly one download
    assert mock_dl.call_count == 2
