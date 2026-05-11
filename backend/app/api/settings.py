from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AppSetting
from app.tasks.scheduler import DEFAULTS

router = APIRouter(prefix="/settings", tags=["settings"])

VALID_INTERVALS = {0, 15, 30, 60, 180, 360, 720, 1440}


class SyncSettings(BaseModel):
    url_sync_interval_minutes: int
    youtube_sync_interval_minutes: int
    download_gain_percent: float
    ffmpeg_threads: int
    celery_worker_concurrency: int
    discord_webhook_url: str
    notify_on_download_complete: bool
    notify_on_download_failed: bool
    notify_on_db_error: bool
    notify_on_youtube_auth_expired: bool

    @field_validator("url_sync_interval_minutes", "youtube_sync_interval_minutes")
    @classmethod
    def must_be_valid_interval(cls, v: int) -> int:
        if v not in VALID_INTERVALS:
            raise ValueError(f"Must be one of {sorted(VALID_INTERVALS)}")
        return v


class SyncSettingsUpdate(BaseModel):
    url_sync_interval_minutes: int | None = None
    youtube_sync_interval_minutes: int | None = None
    download_gain_percent: float | None = None
    ffmpeg_threads: int | None = None
    celery_worker_concurrency: int | None = None
    discord_webhook_url: str | None = None
    notify_on_download_complete: bool | None = None
    notify_on_download_failed: bool | None = None
    notify_on_db_error: bool | None = None
    notify_on_youtube_auth_expired: bool | None = None

    @field_validator("url_sync_interval_minutes", "youtube_sync_interval_minutes", mode="before")
    @classmethod
    def must_be_valid_interval(cls, v: int | None) -> int | None:
        if v is not None and v not in VALID_INTERVALS:
            raise ValueError(f"Must be one of {sorted(VALID_INTERVALS)}")
        return v

    @field_validator("download_gain_percent")
    @classmethod
    def gain_must_be_non_negative(cls, v: float | None) -> float | None:
        if v is not None and v < 0:
            raise ValueError("Must be >= 0")
        return v

    @field_validator("ffmpeg_threads", "celery_worker_concurrency")
    @classmethod
    def must_be_non_negative(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("Must be >= 0")
        return v


def _get_bool(db: Session, key: str) -> bool:
    row = db.get(AppSetting, key)
    value = row.value if row else DEFAULTS[key]
    return value.lower() in ("true", "1")


def _read(db: Session) -> SyncSettings:
    def get(key: str) -> str:
        row = db.get(AppSetting, key)
        return row.value if row else DEFAULTS[key]

    return SyncSettings(
        url_sync_interval_minutes=int(get("url_sync_interval_minutes")),
        youtube_sync_interval_minutes=int(get("youtube_sync_interval_minutes")),
        download_gain_percent=float(get("download_gain_percent")),
        ffmpeg_threads=int(get("ffmpeg_threads")),
        celery_worker_concurrency=int(get("celery_worker_concurrency")),
        discord_webhook_url=get("discord_webhook_url"),
        notify_on_download_complete=_get_bool(db, "notify_on_download_complete"),
        notify_on_download_failed=_get_bool(db, "notify_on_download_failed"),
        notify_on_db_error=_get_bool(db, "notify_on_db_error"),
        notify_on_youtube_auth_expired=_get_bool(db, "notify_on_youtube_auth_expired"),
    )


@router.get("", response_model=SyncSettings)
def get_settings(db: Session = Depends(get_db)):
    return _read(db)


@router.patch("", response_model=SyncSettings)
def update_settings(payload: SyncSettingsUpdate, db: Session = Depends(get_db)):
    updates = payload.model_dump(exclude_none=True)
    for key, value in updates.items():
        str_value = ("true" if value else "false") if isinstance(value, bool) else str(value)
        row = db.get(AppSetting, key)
        if row:
            row.value = str_value
        else:
            db.add(AppSetting(key=key, value=str_value))
    db.commit()
    return _read(db)
