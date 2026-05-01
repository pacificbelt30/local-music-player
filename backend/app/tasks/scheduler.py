from datetime import datetime, timezone, timedelta

from app.database import SessionLocal
from app.models import AppSetting, UrlSource, YoutubePlaylistSync
from app.tasks.celery_app import celery_app

DEFAULTS = {
    "url_sync_interval_minutes": "60",
    "youtube_sync_interval_minutes": "60",
    "download_gain_percent": "0",
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
