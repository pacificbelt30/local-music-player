from app.database import SessionLocal
from app.models import UrlSource
from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.scheduler.periodic_playlist_refresh")
def periodic_playlist_refresh() -> None:
    """Hourly task: re-resolve playlists and channels for new content."""
    db = SessionLocal()
    try:
        sources = db.query(UrlSource).filter(
            UrlSource.sync_enabled == True,  # noqa: E712
            UrlSource.url_type.in_(["playlist", "channel"]),
        ).all()

        for source in sources:
            from app.tasks.download import resolve_url
            resolve_url.apply_async(args=[source.id])
    finally:
        db.close()
