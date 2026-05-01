from datetime import datetime, timezone
from pathlib import Path

import redis as redis_lib
import yt_dlp

from app.config import settings
from app.database import SessionLocal
from app.models import DownloadJob, Track, UrlSource, PlaylistTrack
from app.services import ytdlp_service
from app.tasks.celery_app import celery_app

_redis = redis_lib.from_url(settings.redis_url, decode_responses=True)


def _download_base_path(source: UrlSource | None) -> Path:
    if not source:
        return settings.downloads_path / "手動"

    if source.url_type in ("playlist", "channel"):
        name = source.title or f"source-{source.id}"
    else:
        name = "手動"

    safe_name = yt_dlp.utils.sanitize_filename(name, restricted=True) or "手動"
    return settings.downloads_path / safe_name


@celery_app.task(name="app.tasks.download.resolve_url", bind=True, max_retries=2)
def resolve_url(self, url_source_id: int) -> None:
    db = SessionLocal()
    try:
        source = db.get(UrlSource, url_source_id)
        if not source:
            return

        entries = ytdlp_service.resolve_url(source.url)

        # Update url_type and title from first resolved entry
        if entries:
            source.url_type = entries[0].get("url_type", "video")
            if len(entries) > 1:
                source.url_type = "playlist"
            source.title = entries[0].get("playlist_title") or entries[0].get("title")
        source.last_synced = datetime.now(timezone.utc)
        db.commit()

        for entry in entries:
            youtube_id = entry["id"]
            # INSERT OR IGNORE semantics: skip if already exists
            existing = db.query(DownloadJob).filter_by(youtube_id=youtube_id).first()
            if existing:
                continue

            job = DownloadJob(
                url_source_id=url_source_id,
                youtube_id=youtube_id,
                title=entry.get("title"),
                status="pending",
            )
            db.add(job)
            db.flush()

            # Enqueue download task
            task = download_track.apply_async(
                args=[job.id],
                countdown=0,
            )
            job.celery_task_id = task.id
            db.commit()

    except Exception as exc:
        db.rollback()
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


@celery_app.task(name="app.tasks.download.download_track", bind=True, max_retries=3)
def download_track(self, job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.get(DownloadJob, job_id)
        if not job:
            return

        source = db.get(UrlSource, job.url_source_id) if job.url_source_id else None
        audio_format = source.audio_format if source else "mp3"
        audio_quality = source.audio_quality if source else "192"

        job.status = "downloading"
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        def progress_hook(d: dict) -> None:
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 1
                downloaded = d.get("downloaded_bytes", 0)
                pct = round(downloaded / total * 100, 1)
                _redis.setex(f"job:{job_id}:progress", 300, pct)

        metadata = ytdlp_service.download_track(
            youtube_id=job.youtube_id,
            audio_format=audio_format,
            audio_quality=audio_quality,
            progress_hook=progress_hook,
            base_path=_download_base_path(source),
        )

        # Upsert track record
        track = db.query(Track).filter_by(youtube_id=job.youtube_id).first()
        if not track:
            track = Track(youtube_id=job.youtube_id)
            db.add(track)

        for key, value in metadata.items():
            if key != "youtube_id":
                setattr(track, key, value)
        db.flush()

        # Link track to playlist if applicable
        if job.url_source_id:
            existing_link = db.query(PlaylistTrack).filter_by(
                url_source_id=job.url_source_id, track_id=track.id
            ).first()
            if not existing_link:
                db.add(PlaylistTrack(url_source_id=job.url_source_id, track_id=track.id))

        job.status = "complete"
        job.progress_pct = 100.0
        job.finished_at = datetime.now(timezone.utc)
        _redis.delete(f"job:{job_id}:progress")
        db.commit()

    except Exception as exc:
        db.rollback()
        if job:
            job.status = "failed"
            job.error_message = str(exc)[:500]
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
        raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))
    finally:
        db.close()
