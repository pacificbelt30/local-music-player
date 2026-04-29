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
