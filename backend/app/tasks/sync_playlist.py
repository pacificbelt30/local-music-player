"""Celery tasks for YouTube playlist sync."""

import os
import shutil
from uuid import uuid4
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import httpx
import redis as redis_lib
import sqlalchemy.exc

from app.config import settings
from app.database import SessionLocal
from app.models import AppSetting, PlaylistSyncTrack, YoutubePlaylistSync
from app.services import sync_dirs, youtube_api_service, ytdlp_service
from app.services.notification import notify
from app.tasks.celery_app import celery_app
from app.tasks.scheduler import DEFAULTS
from app.services.task_lease import exclusive_task, check_lease
from app.services import sync_history

_redis = redis_lib.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_timeout=5,
    socket_connect_timeout=5,
)
_DEFAULT_GAIN_PERCENT = "0"
_DEFAULT_SILENCE_TRIM_START_SECS = "2.5"
_DEFAULT_SILENCE_TRIM_END_SECS = "2.5"


def _sync_dir_name(db, sync: YoutubePlaylistSync | None, audio_format: str) -> str:
    """Directory name for a sync's downloads.

    Normally this is sync.dir_name, fixed when the sync was created. Legacy
    rows created before dir_name existed fall back to the old dynamic rule:
    append the format when another sync shares the same playlist name.
    """
    if sync and sync.dir_name:
        return sync.dir_name

    playlist_name = sync.playlist_name if sync else "unknown"
    format_suffix = None
    if sync:
        name_collision = (
            db.query(YoutubePlaylistSync)
            .filter(
                YoutubePlaylistSync.id != sync.id,
                YoutubePlaylistSync.playlist_name == sync.playlist_name,
            )
            .first()
        )
        if name_collision:
            format_suffix = audio_format
    return sync_dirs.playlist_sync_dir_name(playlist_name, format_suffix)


@celery_app.task(
    name="app.tasks.sync_playlist.sync_youtube_playlist", bind=True, max_retries=2
)
@exclusive_task(lambda: _redis, "playlist-sync")
def sync_youtube_playlist(self, playlist_sync_id: int, manual: bool = False) -> None:
    """Sync a YouTube playlist: download new tracks, mark removed tracks."""
    db = SessionLocal()
    try:
        sync = db.get(YoutubePlaylistSync, playlist_sync_id)
        if not sync or (not sync.enabled and not manual):
            return

        source_identity = sync.playlist_id
        if sync.source_type == "url":
            info = ytdlp_service.get_playlist_info(sync.source_url)
            remote_items = info["entries"]
        else:
            access_token = youtube_api_service.get_fresh_access_token(db)
            if not access_token:
                return
            remote_items = youtube_api_service.get_playlist_items(
                sync.playlist_id, access_token
            )
        check_lease()
        db.rollback()
        sync = db.get(YoutubePlaylistSync, playlist_sync_id)
        if not sync or (not sync.enabled and not manual):
            return
        if sync.playlist_id != source_identity:
            return
        remote_ids = {item["youtube_id"] for item in remote_items}

        existing = {
            t.youtube_id: t
            for t in db.query(PlaylistSyncTrack)
            .filter_by(playlist_sync_id=sync.id)
            .all()
        }

        # Collect track IDs that need download tasks dispatched after commit
        tracks_to_download: list[int] = []
        added, removed = [], []

        # Add new tracks
        for item in remote_items:
            vid = item["youtube_id"]
            if vid in existing:
                # Update position if changed and not removed
                t = existing[vid]
                if t.excluded:
                    t.position = item["position"]
                    continue
                active = t.status != "complete" and _redis.exists(
                    f"lmp:playlist-track:{t.id}"
                )
                if active:
                    t.position = item["position"]
                    continue
                if t.status == "downloading":
                    # A restarted worker no longer owns this attempt. Requeue
                    # through the normal UI/scheduler path after lease expiry.
                    t.status = "failed"
                if t.status == "removed":
                    t.status = "complete" if sync_history.retained(t) else "pending"
                    t.removed_at = None
                    added.append({"id": t.id, "title": t.title})
                    if t.status == "pending":
                        t.file_path = None
                    t.error_message = None
                    t.added_at = datetime.now(timezone.utc)
                    db.flush()
                    if t.status == "pending":
                        tracks_to_download.append(t.id)
                elif t.status == "failed":
                    # Retry failed tracks on next sync
                    t.status = "pending"
                    t.error_message = None
                    t.added_at = datetime.now(timezone.utc)
                    tracks_to_download.append(t.id)
                elif (
                    t.status == "pending"
                    and not t.celery_task_id
                    and t.id not in tracks_to_download
                ):
                    tracks_to_download.append(t.id)
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
            # Register so a duplicate youtube_id later in the same playlist is
            # treated as an existing track instead of a second INSERT, which
            # would violate the UNIQUE(playlist_sync_id, youtube_id) constraint.
            existing[vid] = track
            tracks_to_download.append(track.id)
            added.append({"id": track.id, "title": track.title})

        # Remove tracks no longer in the playlist
        for youtube_id, track in existing.items():
            if (
                youtube_id not in remote_ids
                and track.status != "removed"
                and not track.keep_local
            ):
                track.status = "removed"
                track.removed_at = datetime.now(timezone.utc)
                removed.append({"id": track.id, "title": track.title})

        if added or removed:
            sync_history.record(db, sync.id, "sync", added=added, removed=removed)
        sync.last_synced = datetime.now(timezone.utc)
        sync.last_error = None
        db.commit()

        # Dispatch download tasks after commit so workers can find the records
        for track_id in tracks_to_download:
            enqueue_playlist_track(
                db, db.get(PlaylistSyncTrack, track_id), manual=manual
            )

    except httpx.HTTPStatusError as exc:
        db.rollback()
        # 400 from the token endpoint means the refresh token is invalid/revoked — permanent error, no retry
        if exc.response.status_code == 400 and "oauth2.googleapis.com/token" in str(
            exc.request.url
        ):
            sync = db.get(YoutubePlaylistSync, playlist_sync_id)
            if sync:
                sync.last_error = (
                    "YouTubeの認証トークンが無効または失効しています。"
                    " YouTubeアカウントの設定から再接続してください。"
                    f" (詳細: {exc})"
                )
                db.commit()
            notify(
                "notify_on_youtube_auth_expired",
                "YouTube認証切れ",
                f"プレイリスト同期でYouTube OAuthトークンが失効しました。再認証が必要です。\nプレイリスト: {sync.playlist_name if sync else playlist_sync_id}",
                0xFEE75C,
            )
            return
        sync = db.get(YoutubePlaylistSync, playlist_sync_id)
        if sync:
            sync.last_error = str(exc)[:500]
            sync_history.failure(db, sync.id, "fetch_failed", error=sync.last_error)
            db.commit()
        raise self.retry(exc=exc, countdown=60)
    except sqlalchemy.exc.SQLAlchemyError as exc:
        db.rollback()
        notify(
            "notify_on_db_error",
            "DB障害",
            f"プレイリスト同期タスク (id={playlist_sync_id}) でDB障害が発生しました\n```{str(exc)[:300]}```",
            0xFEE75C,
        )
        raise self.retry(exc=exc, countdown=60)
    except Exception as exc:
        db.rollback()
        sync = db.get(YoutubePlaylistSync, playlist_sync_id)
        if sync:
            sync.last_error = str(exc)[:500]
            sync_history.failure(db, sync.id, "fetch_failed", error=sync.last_error)
            db.commit()
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


def enqueue_playlist_track(db, track: PlaylistSyncTrack, manual: bool = False) -> None:
    """Persist attempt metadata before a worker can start the download."""
    if track is None:
        return
    record_id = track.id
    task_id = str(uuid4())
    claimed = (
        db.query(PlaylistSyncTrack)
        .filter(
            PlaylistSyncTrack.id == track.id,
            PlaylistSyncTrack.status != "downloading",
            PlaylistSyncTrack.excluded == False,
        )
        .update(
            {
                "celery_task_id": task_id,
                "started_at": None,
                "added_at": datetime.now(timezone.utc),
                "status": "pending",
            },
            synchronize_session=False,
        )
    )
    if not claimed:
        db.rollback()
        return
    db.commit()
    try:
        options = {"kwargs": {"manual": True}} if manual else {}
        download_playlist_sync_track.apply_async(
            args=[record_id], task_id=task_id, **options
        )
    except Exception as exc:
        db.rollback()
        db.query(PlaylistSyncTrack).filter(
            PlaylistSyncTrack.id == record_id,
            PlaylistSyncTrack.celery_task_id == task_id,
            PlaylistSyncTrack.status != "downloading",
        ).update(
            {"status": "failed", "error_message": str(exc)[:500]},
            synchronize_session=False,
        )
        db.commit()
        raise


def _retry_current_download(self, track_id):
    # A newer queued attempt may arrive during the prior attempt's short
    # handover. Retry only that current request; obsolete duplicates can end.
    if not self.request.id:
        return
    db = SessionLocal()
    try:
        track = db.get(PlaylistSyncTrack, track_id)
        current = (
            track is not None
            and track.status == "pending"
            and track.celery_task_id == self.request.id
        )
    finally:
        db.close()
    if current:
        raise self.retry(countdown=2)


@celery_app.task(
    name="app.tasks.sync_playlist.download_playlist_sync_track",
    bind=True,
    max_retries=3,
)
@exclusive_task(lambda: _redis, "playlist-track", on_busy=_retry_current_download)
def download_playlist_sync_track(self, track_id: int, manual: bool = False) -> None:
    """Download a single PlaylistSyncTrack using yt-dlp into the playlists directory."""
    db = SessionLocal()
    track: PlaylistSyncTrack | None = None
    staging = None
    sync_id = None
    attempt_id = None
    try:
        track = db.get(PlaylistSyncTrack, track_id)
        if (
            not track
            or track.excluded
            or track.status in ("complete", "removed", "skipped")
        ):
            return

        attempt_id = track.celery_task_id
        if self.request.id and attempt_id and self.request.id != attempt_id:
            return
        recovering = bool(track.error_message)
        sync = db.get(YoutubePlaylistSync, track.playlist_sync_id)
        if sync is None:
            return
        sync_id = sync.id
        if not sync.enabled and not manual:
            track.status = "pending"
            track.celery_task_id = None
            db.commit()
            return
        audio_format = sync.audio_format if sync else "mp3"
        audio_quality = sync.audio_quality if sync else "192"
        gain_row = db.get(AppSetting, "download_gain_percent")
        gain_percent = float(gain_row.value if gain_row else _DEFAULT_GAIN_PERCENT)
        start_row = db.get(AppSetting, "silence_trim_start_secs")
        silence_trim_start_secs = float(
            start_row.value if start_row else _DEFAULT_SILENCE_TRIM_START_SECS
        )
        end_row = db.get(AppSetting, "silence_trim_end_secs")
        silence_trim_end_secs = float(
            end_row.value if end_row else _DEFAULT_SILENCE_TRIM_END_SECS
        )
        ffmpeg_threads_row = db.get(AppSetting, "ffmpeg_threads")
        ffmpeg_threads = int(
            ffmpeg_threads_row.value
            if ffmpeg_threads_row
            else DEFAULTS["ffmpeg_threads"]
        )
        ffmpeg_memory_row = db.get(AppSetting, "ffmpeg_memory_limit_mb")
        ffmpeg_memory_limit_mb = int(
            ffmpeg_memory_row.value
            if ffmpeg_memory_row
            else DEFAULTS["ffmpeg_memory_limit_mb"]
        )
        ffmpeg_concurrency_row = db.get(AppSetting, "celery_worker_concurrency")
        ffmpeg_concurrent_processes = int(
            ffmpeg_concurrency_row.value
            if ffmpeg_concurrency_row
            else DEFAULTS["celery_worker_concurrency"]
        )

        # Store in downloads/{dir_name}/, fixed at sync creation
        playlist_name = sync.playlist_name if sync else "unknown"
        safe_playlist_name = _sync_dir_name(db, sync, audio_format)
        base_path = settings.downloads_path / safe_playlist_name
        base_path.mkdir(parents=True, exist_ok=True)

        claimed = (
            db.query(PlaylistSyncTrack)
            .filter(
                PlaylistSyncTrack.id == track_id,
                PlaylistSyncTrack.celery_task_id == attempt_id,
                PlaylistSyncTrack.excluded == False,
                PlaylistSyncTrack.status.notin_(("complete", "removed", "skipped")),
            )
            .update(
                {
                    "status": "downloading",
                    "started_at": datetime.now(timezone.utc),
                    "celery_task_id": self.request.id or attempt_id,
                },
                synchronize_session=False,
            )
        )
        if not claimed:
            db.rollback()
            return
        db.commit()

        def progress_hook(d: dict) -> None:
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 1
                downloaded = d.get("downloaded_bytes", 0)
                pct = round(downloaded / total * 100, 1)
                _redis.setex(f"pstrack:{track_id}:progress", 300, pct)

        attempt_id = track.celery_task_id
        for orphan in base_path.glob(f".lmp-{track_id}-*"):
            if orphan.is_dir():
                shutil.rmtree(orphan)
        staging = TemporaryDirectory(prefix=f".lmp-{track_id}-", dir=base_path)
        metadata = ytdlp_service.download_track(
            youtube_id=track.youtube_id,
            audio_format=audio_format,
            audio_quality=audio_quality,
            gain_percent=gain_percent,
            silence_trim_start_secs=silence_trim_start_secs,
            silence_trim_end_secs=silence_trim_end_secs,
            progress_hook=progress_hook,
            base_path=Path(staging.name),
            ffmpeg_threads=ffmpeg_threads,
            ffmpeg_memory_limit_mb=ffmpeg_memory_limit_mb,
            ffmpeg_concurrent_processes=ffmpeg_concurrent_processes,
        )

        check_lease()
        db.rollback()
        track = db.get(PlaylistSyncTrack, track_id)
        if track is not None and track.celery_task_id != attempt_id:
            return
        if track is None or track.status == "removed":
            deleted = db.get(AppSetting, f"deleted-download:{attempt_id}")
            if track is not None or (deleted is not None and deleted.value == "files"):
                _delete_sync_track_file(
                    SimpleNamespace(
                        file_path=metadata.get("file_path"),
                        thumbnail_path=metadata.get("thumbnail_path"),
                    )
                )
            elif staging is not None:
                for file in Path(staging.name).iterdir():
                    file.replace(base_path / file.name)
            if deleted is not None:
                db.delete(deleted)
                db.commit()
            return
        # Publish only after checking the row still exists. Each attempt writes
        # into its own temporary directory, so expired workers cannot corrupt it.
        moves = [(file, base_path / file.name) for file in Path(staging.name).iterdir()]
        for file, target in moves:
            for key in ("file_path", "thumbnail_path"):
                if metadata.get(key) == str(file):
                    metadata[key] = str(target)
        updated = (
            db.query(PlaylistSyncTrack)
            .filter(
                PlaylistSyncTrack.id == track_id,
                PlaylistSyncTrack.status != "removed",
                PlaylistSyncTrack.celery_task_id == attempt_id,
            )
            .update(
                {
                    "status": "complete",
                    "file_path": metadata["file_path"],
                    "thumbnail_path": metadata.get("thumbnail_path"),
                },
                synchronize_session=False,
            )
        )
        if not updated:
            deleted = db.get(AppSetting, f"deleted-download:{attempt_id}")
            if deleted is not None and deleted.value == "files":
                _delete_sync_track_file(
                    SimpleNamespace(
                        file_path=metadata.get("file_path"),
                        thumbnail_path=metadata.get("thumbnail_path"),
                    )
                )
            return
        check_lease()
        for file, target in moves:
            file.replace(target)
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
        if recovering:
            sync_history.record(
                db,
                sync_id,
                "download_recovered",
                tracks=[{"id": track.id, "title": track.title}],
            )
        db.commit()

        notify(
            "notify_on_download_complete",
            "ダウンロード完了",
            f"**{track.title}**" + (f"\nプレイリスト: {playlist_name}" if sync else ""),
            0x57F287,
        )

    except sqlalchemy.exc.SQLAlchemyError as exc:
        db.rollback()
        notify(
            "notify_on_db_error",
            "DB障害",
            f"プレイリストトラックDLタスク (track_id={track_id}) でDB障害が発生しました\n```{str(exc)[:300]}```",
            0xFEE75C,
        )
        raise self.retry(exc=exc, countdown=30 * (2**self.request.retries))
    except Exception as exc:
        db.rollback()
        track = db.get(PlaylistSyncTrack, track_id)
        if track is None or track.celery_task_id != attempt_id:
            return
        if track:
            track.status = "failed"
            track.error_message = str(exc)[:500]
            sync_history.failure(
                db,
                track.playlist_sync_id,
                "download_failed",
                tracks=[{"id": track.id, "title": track.title}],
                error=track.error_message,
            )
            try:
                db.commit()
            except Exception:
                pass
        notify(
            "notify_on_download_failed",
            "ダウンロード失敗",
            f"**{track.title if track else track_id}**\n```{str(exc)[:300]}```",
            0xED4245,
        )
        raise self.retry(exc=exc, countdown=30 * (2**self.request.retries))
    finally:
        db.close()
        if staging is not None:
            staging.cleanup()


def _delete_sync_track_file(track: PlaylistSyncTrack) -> None:
    """Delete audio file and thumbnail for a playlist sync track."""
    for path in [track.file_path, track.thumbnail_path]:
        if path and os.path.exists(path):
            os.remove(path)
    if track.file_path:
        p = Path(track.file_path)
        info_json = p.with_suffix(".info.json")
        if info_json.exists():
            info_json.unlink()
