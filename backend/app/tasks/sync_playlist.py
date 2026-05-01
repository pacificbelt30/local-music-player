"""Celery tasks for YouTube playlist sync."""
import os
from datetime import datetime, timezone
from pathlib import Path

import redis as redis_lib
import yt_dlp

from app.config import settings
from app.database import SessionLocal
from app.models import PlaylistSyncTrack, YoutubePlaylistSync
from app.services import youtube_api_service, ytdlp_service
from app.tasks.celery_app import celery_app

_redis = redis_lib.from_url(settings.redis_url, decode_responses=True)


@celery_app.task(name="app.tasks.sync_playlist.sync_youtube_playlist", bind=True, max_retries=2)
def sync_youtube_playlist(self, playlist_sync_id: int) -> None:
    """Sync a YouTube playlist: download new tracks, mark removed tracks."""
    db = SessionLocal()
    try:
        sync = db.get(YoutubePlaylistSync, playlist_sync_id)
        if not sync or not sync.enabled:
            return

        access_token = youtube_api_service.get_fresh_access_token(db)
        if not access_token:
            return

        remote_items = youtube_api_service.get_playlist_items(sync.playlist_id, access_token)
        remote_ids = {item["youtube_id"] for item in remote_items}

        existing = {t.youtube_id: t for t in db.query(PlaylistSyncTrack).filter_by(playlist_sync_id=sync.id).all()}

        # Add new tracks
        for item in remote_items:
            vid = item["youtube_id"]
            if vid in existing:
                # Update position if changed and not removed
                t = existing[vid]
                if t.status == "removed":
                    t.status = "pending"
                    t.file_path = None
                    t.error_message = None
                    db.flush()
                    download_playlist_sync_track.apply_async(args=[t.id])
                else:
                    t.position = item["position"]
                continue

            track = PlaylistSyncTrack(
                playlist_sync_id=sync.id,
                youtube_id=vid,
                title=item["title"],
                position=item["position"],
                status="pending",
            )
            db.add(track)
            db.flush()
            download_playlist_sync_track.apply_async(args=[track.id])

        # Remove tracks no longer in the playlist
        for youtube_id, track in existing.items():
            if youtube_id not in remote_ids and track.status != "removed":
                _delete_sync_track_file(track)
                track.status = "removed"

        sync.last_synced = datetime.now(timezone.utc)
        db.commit()

    except Exception as exc:
        db.rollback()
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


@celery_app.task(name="app.tasks.sync_playlist.download_playlist_sync_track", bind=True, max_retries=3)
def download_playlist_sync_track(self, track_id: int) -> None:
    """Download a single PlaylistSyncTrack using yt-dlp into the playlists directory."""
    db = SessionLocal()
    try:
        track = db.get(PlaylistSyncTrack, track_id)
        if not track or track.status in ("complete", "removed"):
            return

        sync = db.get(YoutubePlaylistSync, track.playlist_sync_id)
        audio_format = sync.audio_format if sync else "mp3"
        audio_quality = sync.audio_quality if sync else "192"

        # Store in downloads/{playlist_name}/
        playlist_name = sync.playlist_name if sync else "unknown"
        safe_playlist_name = yt_dlp.utils.sanitize_filename(playlist_name, restricted=True) or "unknown"
        base_path = settings.downloads_path / safe_playlist_name
        base_path.mkdir(parents=True, exist_ok=True)

        track.status = "downloading"
        db.commit()

        def progress_hook(d: dict) -> None:
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 1
                downloaded = d.get("downloaded_bytes", 0)
                pct = round(downloaded / total * 100, 1)
                _redis.setex(f"pstrack:{track_id}:progress", 300, pct)

        metadata = ytdlp_service.download_track(
            youtube_id=track.youtube_id,
            audio_format=audio_format,
            audio_quality=audio_quality,
            progress_hook=progress_hook,
            base_path=base_path,
        )

        track.title = metadata["title"]
        track.artist = metadata.get("artist")
        track.duration_secs = metadata.get("duration_secs")
        track.file_path = metadata["file_path"]
        track.file_format = metadata.get("file_format")
        track.file_size_bytes = metadata.get("file_size_bytes")
        track.thumbnail_path = metadata.get("thumbnail_path")
        track.status = "complete"
        track.downloaded_at = datetime.now(timezone.utc)
        track.error_message = None
        _redis.delete(f"pstrack:{track_id}:progress")
        db.commit()

    except Exception as exc:
        db.rollback()
        if track:
            track.status = "failed"
            track.error_message = str(exc)[:500]
            db.commit()
        raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))
    finally:
        db.close()


def _delete_sync_track_file(track: PlaylistSyncTrack) -> None:
    """Delete audio file and thumbnail for a playlist sync track."""
    for path in [track.file_path, track.thumbnail_path]:
        if path and os.path.exists(path):
            os.remove(path)
    if track.file_path:
        p = Path(track.file_path)
        info_json = p.with_suffix("").with_suffix(".info.json")
        if info_json.exists():
            info_json.unlink()
