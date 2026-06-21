"""Celery tasks that re-process already-downloaded library content."""
from app.database import SessionLocal
from app.models import DownloadJob, PlaylistSyncTrack, Track
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
