"""Celery tasks that re-process already-downloaded library content."""
from app.database import SessionLocal
from app.models import AppSetting, DownloadJob, PlaylistSyncTrack, Track
from app.services.ytdlp_service import VIDEO_FORMATS
from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.maintenance.requeue_silence_trim_changed")
def requeue_silence_trim_changed() -> None:
    """Re-download every completed audio track from YouTube so the
    currently configured silence-trim seconds get applied (the ffmpeg
    filter only runs at download time, not against already-saved files).
    Video tracks are skipped since the filter never applies to them.
    """
    from app.tasks.download import download_track
    from app.tasks.sync_playlist import download_playlist_sync_track

    db = SessionLocal()
    try:
        jobs = db.query(DownloadJob).filter(DownloadJob.status == "complete").all()
        jobs_to_requeue = []
        for job in jobs:
            track = db.query(Track).filter_by(youtube_id=job.youtube_id).first()
            if track and track.file_format in VIDEO_FORMATS:
                continue
            jobs_to_requeue.append(job)

        for job in jobs_to_requeue:
            job.status = "pending"
            job.progress_pct = 0.0
            job.error_message = None
        db.commit()

        for job in jobs_to_requeue:
            task = download_track.apply_async(args=[job.id])
            job.celery_task_id = task.id
        if jobs_to_requeue:
            db.commit()

        sync_tracks = db.query(PlaylistSyncTrack).filter(PlaylistSyncTrack.status == "complete").all()
        sync_tracks_to_requeue = [t for t in sync_tracks if t.file_format not in VIDEO_FORMATS]

        for track in sync_tracks_to_requeue:
            track.status = "pending"
        if sync_tracks_to_requeue:
            db.commit()

        for track in sync_tracks_to_requeue:
            download_playlist_sync_track.apply_async(args=[track.id])
    finally:
        db.close()


@celery_app.task(name="app.tasks.maintenance.retrim_existing_silence_locally")
def retrim_existing_silence_locally() -> None:
    """Re-apply the currently configured (smaller) silence-trim seconds directly
    to already-downloaded audio files in place, with no redownload from YouTube.
    Safe only when trim seconds were decreased: the now-qualifying short silence
    is still physically present at the edges of the local file, since it was
    never removed under the previous (larger) setting.
    """
    from app.tasks.scheduler import DEFAULTS
    from app.services.ytdlp_service import retrim_audio_file

    db = SessionLocal()
    try:
        start_row = db.get(AppSetting, "silence_trim_start_secs")
        end_row = db.get(AppSetting, "silence_trim_end_secs")
        start_secs = float(start_row.value if start_row else DEFAULTS["silence_trim_start_secs"])
        end_secs = float(end_row.value if end_row else DEFAULTS["silence_trim_end_secs"])
        ffmpeg_threads_row = db.get(AppSetting, "ffmpeg_threads")
        ffmpeg_threads = int(ffmpeg_threads_row.value if ffmpeg_threads_row else DEFAULTS["ffmpeg_threads"])
        ffmpeg_memory_row = db.get(AppSetting, "ffmpeg_memory_limit_mb")
        ffmpeg_memory_limit_mb = int(ffmpeg_memory_row.value if ffmpeg_memory_row else DEFAULTS["ffmpeg_memory_limit_mb"])

        jobs = db.query(DownloadJob).filter(DownloadJob.status == "complete").all()
        for job in jobs:
            track = db.query(Track).filter_by(youtube_id=job.youtube_id).first()
            if not track or track.file_format in VIDEO_FORMATS:
                continue
            new_size = retrim_audio_file(track.file_path, track.file_format, start_secs, end_secs, ffmpeg_threads, ffmpeg_memory_limit_mb)
            if new_size is not None:
                track.file_size_bytes = new_size

        sync_tracks = db.query(PlaylistSyncTrack).filter(PlaylistSyncTrack.status == "complete").all()
        for track in sync_tracks:
            if not track.file_path or track.file_format in VIDEO_FORMATS:
                continue
            new_size = retrim_audio_file(track.file_path, track.file_format, start_secs, end_secs, ffmpeg_threads, ffmpeg_memory_limit_mb)
            if new_size is not None:
                track.file_size_bytes = new_size

        db.commit()
    finally:
        db.close()
