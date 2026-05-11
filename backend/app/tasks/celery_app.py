from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "music_player",
    broker=settings.redis_url,
    backend=settings.redis_result_backend,
    include=["app.tasks.download", "app.tasks.scheduler", "app.tasks.sync_playlist"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_routes={
        "app.tasks.download.*": {"queue": "downloads"},
        "app.tasks.scheduler.*": {"queue": "scheduler"},
        "app.tasks.sync_playlist.*": {"queue": "downloads"},
    },
    beat_schedule={
        "check-playlist-refresh": {
            "task": "app.tasks.scheduler.periodic_playlist_refresh",
            "schedule": crontab(minute="*/5"),
        },
        "check-youtube-playlist-sync": {
            "task": "app.tasks.scheduler.periodic_youtube_playlist_sync",
            "schedule": crontab(minute="*/5"),
        },
    },
)

# Apply worker concurrency from DB if configured (takes effect on worker startup)
try:
    from app.database import SessionLocal as _SessionLocal
    from app.models import AppSetting as _AppSetting
    _db = _SessionLocal()
    _row = _db.get(_AppSetting, "celery_worker_concurrency")
    _concurrency = int(_row.value) if _row and _row.value else 0
    _db.close()
    if _concurrency > 0:
        celery_app.conf.worker_concurrency = _concurrency
except Exception:
    pass
