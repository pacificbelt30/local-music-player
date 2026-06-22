"""Tests for re-downloading the library when silence-trim settings change."""
from unittest.mock import MagicMock, patch

from app.models import AppSetting, DownloadJob, PlaylistSyncTrack, Track, YoutubePlaylistSync


def _job(db, youtube_id="vid1", status="complete", **kwargs):
    job = DownloadJob(youtube_id=youtube_id, status=status, **kwargs)
    db.add(job)
    db.commit()
    return job


def _track(db, youtube_id="vid1", file_format="mp3"):
    track = Track(
        youtube_id=youtube_id, title="Title", file_path=f"/music/{youtube_id}.{file_format}",
        file_format=file_format,
    )
    db.add(track)
    db.commit()
    return track


def _sync_track(db, youtube_id="vid2", status="complete", file_format="mp3"):
    sync = YoutubePlaylistSync(playlist_id="PL1", playlist_name="My List", audio_format=file_format)
    db.add(sync)
    db.commit()
    track = PlaylistSyncTrack(
        playlist_sync_id=sync.id, youtube_id=youtube_id, title="Title",
        status=status, file_format=file_format, file_path=f"/music/{youtube_id}.{file_format}",
    )
    db.add(track)
    db.commit()
    return track


class TestRequeueSilenceTrimChanged:
    def test_requeues_completed_audio_job(self, db):
        from app.tasks.maintenance import requeue_silence_trim_changed
        job = _job(db)
        job_id = job.id
        _track(db)

        with patch("app.tasks.maintenance.SessionLocal", return_value=db):
            with patch("app.tasks.download.download_track.apply_async") as mock_task:
                mock_task.return_value = MagicMock(id="task-1")
                requeue_silence_trim_changed.apply()

        mock_task.assert_called_once_with(args=[job_id])
        refreshed = db.get(DownloadJob, job_id)
        assert refreshed.status == "pending"
        assert refreshed.progress_pct == 0.0

    def test_skips_video_job(self, db):
        from app.tasks.maintenance import requeue_silence_trim_changed
        _job(db)
        _track(db, file_format="mp4")

        with patch("app.tasks.maintenance.SessionLocal", return_value=db):
            with patch("app.tasks.download.download_track.apply_async") as mock_task:
                requeue_silence_trim_changed.apply()

        mock_task.assert_not_called()

    def test_skips_non_complete_job(self, db):
        from app.tasks.maintenance import requeue_silence_trim_changed
        _job(db, status="pending")
        _track(db)

        with patch("app.tasks.maintenance.SessionLocal", return_value=db):
            with patch("app.tasks.download.download_track.apply_async") as mock_task:
                requeue_silence_trim_changed.apply()

        mock_task.assert_not_called()

    def test_requeues_completed_sync_track(self, db):
        from app.tasks.maintenance import requeue_silence_trim_changed
        track = _sync_track(db)
        track_id = track.id

        with patch("app.tasks.maintenance.SessionLocal", return_value=db):
            with patch("app.tasks.sync_playlist.download_playlist_sync_track.apply_async") as mock_task:
                requeue_silence_trim_changed.apply()

        mock_task.assert_called_once_with(args=[track_id])
        refreshed = db.get(PlaylistSyncTrack, track_id)
        assert refreshed.status == "pending"

    def test_skips_video_sync_track(self, db):
        from app.tasks.maintenance import requeue_silence_trim_changed
        _sync_track(db, file_format="webm")

        with patch("app.tasks.maintenance.SessionLocal", return_value=db):
            with patch("app.tasks.sync_playlist.download_playlist_sync_track.apply_async") as mock_task:
                requeue_silence_trim_changed.apply()

        mock_task.assert_not_called()

    def test_skips_removed_sync_track(self, db):
        from app.tasks.maintenance import requeue_silence_trim_changed
        _sync_track(db, status="removed")

        with patch("app.tasks.maintenance.SessionLocal", return_value=db):
            with patch("app.tasks.sync_playlist.download_playlist_sync_track.apply_async") as mock_task:
                requeue_silence_trim_changed.apply()

        mock_task.assert_not_called()


class TestRetrimExistingSilenceLocally:
    def test_retrims_completed_audio_track_in_place(self, db):
        from app.tasks.maintenance import retrim_existing_silence_locally
        db.add(AppSetting(key="silence_trim_start_secs", value="1.0"))
        db.add(AppSetting(key="silence_trim_end_secs", value="1.0"))
        db.commit()
        job = _job(db)
        track = _track(db)
        track_id = track.id
        file_path = track.file_path

        with patch("app.tasks.maintenance.SessionLocal", return_value=db):
            with patch("app.services.ytdlp_service.retrim_audio_file", return_value=999) as mock_retrim:
                retrim_existing_silence_locally.apply()

        mock_retrim.assert_called_once_with(file_path, "mp3", 1.0, 1.0, 1, 0)
        refreshed = db.get(Track, track_id)
        assert refreshed.file_size_bytes == 999

    def test_skips_video_job(self, db):
        from app.tasks.maintenance import retrim_existing_silence_locally
        _job(db)
        _track(db, file_format="mp4")

        with patch("app.tasks.maintenance.SessionLocal", return_value=db):
            with patch("app.services.ytdlp_service.retrim_audio_file") as mock_retrim:
                retrim_existing_silence_locally.apply()

        mock_retrim.assert_not_called()

    def test_skips_non_complete_job(self, db):
        from app.tasks.maintenance import retrim_existing_silence_locally
        _job(db, status="pending")
        _track(db)

        with patch("app.tasks.maintenance.SessionLocal", return_value=db):
            with patch("app.services.ytdlp_service.retrim_audio_file") as mock_retrim:
                retrim_existing_silence_locally.apply()

        mock_retrim.assert_not_called()

    def test_retrims_completed_sync_track_in_place(self, db):
        from app.tasks.maintenance import retrim_existing_silence_locally
        track = _sync_track(db)
        track_id = track.id

        with patch("app.tasks.maintenance.SessionLocal", return_value=db):
            with patch("app.services.ytdlp_service.retrim_audio_file", return_value=555) as mock_retrim:
                retrim_existing_silence_locally.apply()

        mock_retrim.assert_called_once()
        refreshed = db.get(PlaylistSyncTrack, track_id)
        assert refreshed.file_size_bytes == 555

    def test_skips_video_sync_track(self, db):
        from app.tasks.maintenance import retrim_existing_silence_locally
        _sync_track(db, file_format="webm")

        with patch("app.tasks.maintenance.SessionLocal", return_value=db):
            with patch("app.services.ytdlp_service.retrim_audio_file") as mock_retrim:
                retrim_existing_silence_locally.apply()

        mock_retrim.assert_not_called()

    def test_skips_removed_sync_track(self, db):
        from app.tasks.maintenance import retrim_existing_silence_locally
        _sync_track(db, status="removed")

        with patch("app.tasks.maintenance.SessionLocal", return_value=db):
            with patch("app.services.ytdlp_service.retrim_audio_file") as mock_retrim:
                retrim_existing_silence_locally.apply()

        mock_retrim.assert_not_called()

    def test_no_change_when_retrim_returns_none(self, db):
        from app.tasks.maintenance import retrim_existing_silence_locally
        _job(db)
        track = _track(db)
        track_id = track.id
        original_size = track.file_size_bytes

        with patch("app.tasks.maintenance.SessionLocal", return_value=db):
            with patch("app.services.ytdlp_service.retrim_audio_file", return_value=None):
                retrim_existing_silence_locally.apply()

        refreshed = db.get(Track, track_id)
        assert refreshed.file_size_bytes == original_size
