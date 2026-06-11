"""Celery tasks for YouTube playlist sync."""
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
import redis as redis_lib
import sqlalchemy.exc
import yt_dlp

from app.config import settings
from app.database import SessionLocal
from app.models import AppSetting, PlaylistSyncTrack, YoutubePlaylistSync
from app.services import youtube_api_service, ytdlp_service
from app.services.notification import notify
from app.tasks.celery_app import celery_app

_redis = redis_lib.from_url(settings.redis_url, decode_responses=True)
_DEFAULT_GAIN_PERCENT = "0"


def _playlist_sync_dir_name(playlist_name: str | None, format_suffix: str | None = None) -> str:
    """Build a safe directory name while preserving non-ASCII playlist names.

    When the same playlist is synced in multiple formats the directory name
    would collide, so the format is appended as a suffix (e.g. "Mix [mp4]").
    """
    name = (playlist_name or "").strip()
    base = yt_dlp.utils.sanitize_filename(name, restricted=False) or "unknown"
    if format_suffix:
        return f"{base} [{format_suffix}]"
    return base


@celery_app.task(name="app.tasks.sync_playlist.sync_youtube_playlist", bind=True, max_retries=2)
def sync_youtube_playlist(self, playlist_sync_id: int) -> None:
    """Sync a YouTube playlist: download new tracks, mark removed tracks."""
    db = SessionLocal()
    try:
        sync = db.get(YoutubePlaylistSync, playlist_sync_id)
        if not sync or not sync.enabled:
            return

        if sync.source_type == "url":
            info = ytdlp_service.get_playlist_info(sync.source_url)
            remote_items = info["entries"]
        else:
            access_token = youtube_api_service.get_fresh_access_token(db)
            if not access_token:
                return
            remote_items = youtube_api_service.get_playlist_items(sync.playlist_id, access_token)
        remote_ids = {item["youtube_id"] for item in remote_items}

        existing = {t.youtube_id: t for t in db.query(PlaylistSyncTrack).filter_by(playlist_sync_id=sync.id).all()}

        # Collect track IDs that need download tasks dispatched after commit
        tracks_to_download: list[int] = []

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
                    t.added_at = datetime.now(timezone.utc)
                    db.flush()
                    tracks_to_download.append(t.id)
                elif t.status == "failed":
                    # Retry failed tracks on next sync
                    t.status = "pending"
                    t.error_message = None
                    t.added_at = datetime.now(timezone.utc)
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
            tracks_to_download.append(track.id)

        # Remove tracks no longer in the playlist
        for youtube_id, track in existing.items():
            if youtube_id not in remote_ids and track.status != "removed":
                _delete_sync_track_file(track)
                track.status = "removed"

        sync.last_synced = datetime.now(timezone.utc)
        sync.last_error = None
        db.commit()

        # Dispatch download tasks after commit so workers can find the records
        for track_id in tracks_to_download:
            download_playlist_sync_track.apply_async(args=[track_id])

    except httpx.HTTPStatusError as exc:
        db.rollback()
        # 400 from the token endpoint means the refresh token is invalid/revoked — permanent error, no retry
        if exc.response.status_code == 400 and "oauth2.googleapis.com/token" in str(exc.request.url):
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
            db.commit()
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


@celery_app.task(name="app.tasks.sync_playlist.download_playlist_sync_track", bind=True, max_retries=3)
def download_playlist_sync_track(self, track_id: int) -> None:
    """Download a single PlaylistSyncTrack using yt-dlp into the playlists directory."""
    db = SessionLocal()
    track: PlaylistSyncTrack | None = None
    try:
        track = db.get(PlaylistSyncTrack, track_id)
        if not track or track.status in ("complete", "removed"):
            return

        sync = db.get(YoutubePlaylistSync, track.playlist_sync_id)
        audio_format = sync.audio_format if sync else "mp3"
        audio_quality = sync.audio_quality if sync else "192"
        gain_row = db.get(AppSetting, "download_gain_percent")
        gain_percent = float(gain_row.value if gain_row else _DEFAULT_GAIN_PERCENT)

        # Store in downloads/{playlist_name}/ — appending the format when
        # another sync shares the same playlist name (multi-format sync)
        playlist_name = sync.playlist_name if sync else "unknown"
        format_suffix = None
        if sync:
            name_collision = db.query(YoutubePlaylistSync).filter(
                YoutubePlaylistSync.id != sync.id,
                YoutubePlaylistSync.playlist_name == sync.playlist_name,
            ).first()
            if name_collision:
                format_suffix = audio_format
        safe_playlist_name = _playlist_sync_dir_name(playlist_name, format_suffix)
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
            gain_percent=gain_percent,
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
        raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))
    except Exception as exc:
        db.rollback()
        if track:
            track.status = "failed"
            track.error_message = str(exc)[:500]
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
