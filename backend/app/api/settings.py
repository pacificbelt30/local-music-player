from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AppSetting
from app.tasks.scheduler import DEFAULTS

router = APIRouter(prefix="/settings", tags=["settings"])

VALID_INTERVALS = {0, 15, 30, 60, 180, 360, 720, 1440}
SILENCE_TRIM_KEYS = ("silence_trim_start_secs", "silence_trim_end_secs")


class SyncSettings(BaseModel):
    url_sync_interval_minutes: int
    youtube_sync_interval_minutes: int
    download_gain_percent: float
    silence_trim_start_secs: float
    silence_trim_end_secs: float
    ffmpeg_threads: int
    celery_worker_concurrency: int
    discord_webhook_url: str
    notify_on_download_complete: bool
    notify_on_download_failed: bool
    notify_on_db_error: bool
    notify_on_youtube_auth_expired: bool
    notify_on_oauth_expiry_warning: bool
    oauth_expiry_warning_minutes: int
    silence_trim_requeued: bool = False
    silence_trim_retrimmed_locally: bool = False

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
    silence_trim_start_secs: float | None = None
    silence_trim_end_secs: float | None = None
    ffmpeg_threads: int | None = None
    celery_worker_concurrency: int | None = None
    discord_webhook_url: str | None = None
    notify_on_download_complete: bool | None = None
    notify_on_download_failed: bool | None = None
    notify_on_db_error: bool | None = None
    notify_on_youtube_auth_expired: bool | None = None
    notify_on_oauth_expiry_warning: bool | None = None
    oauth_expiry_warning_minutes: int | None = None

    @field_validator("url_sync_interval_minutes", "youtube_sync_interval_minutes", mode="before")
    @classmethod
    def must_be_valid_interval(cls, v: int | None) -> int | None:
        if v is not None and v not in VALID_INTERVALS:
            raise ValueError(f"Must be one of {sorted(VALID_INTERVALS)}")
        return v

    @field_validator("download_gain_percent", "silence_trim_start_secs", "silence_trim_end_secs")
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

    @field_validator("oauth_expiry_warning_minutes")
    @classmethod
    def must_be_positive(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("Must be >= 1")
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
        silence_trim_start_secs=float(get("silence_trim_start_secs")),
        silence_trim_end_secs=float(get("silence_trim_end_secs")),
        ffmpeg_threads=int(get("ffmpeg_threads")),
        celery_worker_concurrency=int(get("celery_worker_concurrency")),
        discord_webhook_url=get("discord_webhook_url"),
        notify_on_download_complete=_get_bool(db, "notify_on_download_complete"),
        notify_on_download_failed=_get_bool(db, "notify_on_download_failed"),
        notify_on_db_error=_get_bool(db, "notify_on_db_error"),
        notify_on_youtube_auth_expired=_get_bool(db, "notify_on_youtube_auth_expired"),
        notify_on_oauth_expiry_warning=_get_bool(db, "notify_on_oauth_expiry_warning"),
        oauth_expiry_warning_minutes=int(get("oauth_expiry_warning_minutes")),
    )


@router.get("", response_model=SyncSettings)
def get_settings(db: Session = Depends(get_db)):
    return _read(db)


@router.patch("", response_model=SyncSettings)
def update_settings(payload: SyncSettingsUpdate, db: Session = Depends(get_db)):
    updates = payload.model_dump(exclude_none=True)

    # Increasing a trim threshold makes trimming less aggressive: audio that was
    # already removed under the old (smaller) setting is gone for good locally,
    # so a full redownload from YouTube is required. Decreasing it makes trimming
    # more aggressive, but the now-qualifying short silence is still physically
    # present in the local file (the old, larger setting never removed it), so it
    # can be trimmed in place with ffmpeg. If both happen at once (one key up, the
    # other down), the redownload path wins since it also re-applies the decrease.
    silence_trim_increased = False
    silence_trim_decreased = False
    for key in SILENCE_TRIM_KEYS:
        if key not in updates:
            continue
        row = db.get(AppSetting, key)
        current = float(row.value if row else DEFAULTS[key])
        new = float(updates[key])
        if new > current:
            silence_trim_increased = True
        elif new < current:
            silence_trim_decreased = True

    for key, value in updates.items():
        str_value = ("true" if value else "false") if isinstance(value, bool) else str(value)
        row = db.get(AppSetting, key)
        if row:
            row.value = str_value
        else:
            db.add(AppSetting(key=key, value=str_value))
    db.commit()

    retrim_locally = False
    if silence_trim_increased:
        from app.tasks.maintenance import requeue_silence_trim_changed
        requeue_silence_trim_changed.apply_async()
    elif silence_trim_decreased:
        from app.tasks.maintenance import retrim_existing_silence_locally
        retrim_existing_silence_locally.apply_async()
        retrim_locally = True

    result = _read(db)
    result.silence_trim_requeued = silence_trim_increased
    result.silence_trim_retrimmed_locally = retrim_locally
    return result
