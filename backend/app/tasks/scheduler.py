from datetime import datetime, timezone, timedelta

from app.database import SessionLocal
from app.models import AppSetting, UrlSource, YoutubePlaylistSync, YouTubeOAuthToken
from app.tasks.celery_app import celery_app

DEFAULTS = {
    "url_sync_interval_minutes": "60",
    "youtube_sync_interval_minutes": "60",
    "download_gain_percent": "0",
    "silence_trim_start_secs": "2.5",
    "silence_trim_end_secs": "2.5",
    "ffmpeg_threads": "1",
    "celery_worker_concurrency": "0",
    "discord_webhook_url": "",
    "notify_on_download_complete": "false",
    "notify_on_download_failed": "true",
    "notify_on_db_error": "true",
    "notify_on_youtube_auth_expired": "true",
    "notify_on_oauth_expiry_warning": "true",
    "oauth_expiry_warning_minutes": "60",
    "oauth_expiry_last_notified_expiry": "",
}


def _get(db, key: str) -> str:
    row = db.get(AppSetting, key)
    return row.value if row else DEFAULTS.get(key, "0")


def _set(db, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.commit()


def _is_due(db, last_run_key: str, interval_minutes: int) -> bool:
    """Return True if enough time has elapsed since last run."""
    if interval_minutes == 0:
        return False
    last_str = _get(db, last_run_key)
    if not last_str or last_str == DEFAULTS.get(last_run_key, ""):
        return True
    try:
        last = datetime.fromisoformat(last_str)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - last) >= timedelta(minutes=interval_minutes)
    except ValueError:
        return True


@celery_app.task(name="app.tasks.scheduler.periodic_playlist_refresh")
def periodic_playlist_refresh() -> None:
    """Check interval, then re-resolve playlists/channels for new content."""
    db = SessionLocal()
    try:
        interval = int(_get(db, "url_sync_interval_minutes"))
        if not _is_due(db, "url_sync_last_run", interval):
            return

        _set(db, "url_sync_last_run", datetime.now(timezone.utc).isoformat())

        sources = db.query(UrlSource).filter(
            UrlSource.sync_enabled == True,  # noqa: E712
            UrlSource.url_type.in_(["playlist", "channel"]),
        ).all()

        for source in sources:
            from app.tasks.download import resolve_url
            resolve_url.apply_async(args=[source.id])
    finally:
        db.close()


@celery_app.task(name="app.tasks.scheduler.periodic_youtube_playlist_sync")
def periodic_youtube_playlist_sync() -> None:
    """Check interval, then sync all enabled YouTube playlist sync configs."""
    db = SessionLocal()
    try:
        interval = int(_get(db, "youtube_sync_interval_minutes"))
        if not _is_due(db, "youtube_sync_last_run", interval):
            return

        _set(db, "youtube_sync_last_run", datetime.now(timezone.utc).isoformat())

        syncs = db.query(YoutubePlaylistSync).filter(
            YoutubePlaylistSync.enabled == True,  # noqa: E712
        ).all()

        for sync in syncs:
            from app.tasks.sync_playlist import sync_youtube_playlist
            sync_youtube_playlist.apply_async(args=[sync.id])
    finally:
        db.close()


@celery_app.task(name="app.tasks.scheduler.periodic_oauth_expiry_check")
def periodic_oauth_expiry_check() -> None:
    """Warn via Discord if the YouTube OAuth token is about to expire."""
    db = SessionLocal()
    try:
        warning_minutes = int(_get(db, "oauth_expiry_warning_minutes"))
        if warning_minutes <= 0:
            return

        token = db.query(YouTubeOAuthToken).first()
        if not token or not token.token_expiry:
            return

        now = datetime.now(timezone.utc)
        expiry = token.token_expiry
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)

        remaining_seconds = (expiry - now).total_seconds()
        if remaining_seconds <= 0:
            return  # already expired — notify_on_youtube_auth_expired handles this

        remaining_minutes = remaining_seconds / 60
        if remaining_minutes > warning_minutes:
            return  # still outside the warning window

        # Avoid spamming: skip if we already notified about this exact token expiry
        last_expiry_str = _get(db, "oauth_expiry_last_notified_expiry")
        if last_expiry_str:
            try:
                last_expiry = datetime.fromisoformat(last_expiry_str)
                if last_expiry.tzinfo is None:
                    last_expiry = last_expiry.replace(tzinfo=timezone.utc)
                if abs((last_expiry - expiry).total_seconds()) < 600:  # same token (within 10 min)
                    return
            except ValueError:
                pass

        from app.services.notification import notify
        notify(
            "notify_on_oauth_expiry_warning",
            "YouTubeトークン期限切れ間近",
            f"YouTube OAuth トークンがあと約 {int(remaining_minutes)} 分で期限切れになります。YouTubeアカウントの設定から再認証してください。",
            0xFEE75C,
        )

        _set(db, "oauth_expiry_last_notified_expiry", expiry.isoformat())
    finally:
        db.close()
