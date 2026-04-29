from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AppSetting
from app.tasks.scheduler import DEFAULTS

router = APIRouter(prefix="/settings", tags=["settings"])

VALID_INTERVALS = {0, 15, 30, 60, 180, 360, 720, 1440}
EDITABLE_KEYS = {"url_sync_interval_minutes", "youtube_sync_interval_minutes"}


class SyncSettings(BaseModel):
    url_sync_interval_minutes: int
    youtube_sync_interval_minutes: int

    @field_validator("url_sync_interval_minutes", "youtube_sync_interval_minutes")
    @classmethod
    def must_be_valid(cls, v: int) -> int:
        if v not in VALID_INTERVALS:
            raise ValueError(f"Must be one of {sorted(VALID_INTERVALS)}")
        return v


class SyncSettingsUpdate(BaseModel):
    url_sync_interval_minutes: int | None = None
    youtube_sync_interval_minutes: int | None = None

    @field_validator("url_sync_interval_minutes", "youtube_sync_interval_minutes", mode="before")
    @classmethod
    def must_be_valid(cls, v: int | None) -> int | None:
        if v is not None and v not in VALID_INTERVALS:
            raise ValueError(f"Must be one of {sorted(VALID_INTERVALS)}")
        return v


def _read(db: Session) -> SyncSettings:
    def get(key: str) -> int:
        row = db.get(AppSetting, key)
        return int(row.value if row else DEFAULTS[key])

    return SyncSettings(
        url_sync_interval_minutes=get("url_sync_interval_minutes"),
        youtube_sync_interval_minutes=get("youtube_sync_interval_minutes"),
    )


@router.get("", response_model=SyncSettings)
def get_settings(db: Session = Depends(get_db)):
    return _read(db)


@router.patch("", response_model=SyncSettings)
def update_settings(payload: SyncSettingsUpdate, db: Session = Depends(get_db)):
    updates = payload.model_dump(exclude_none=True)
    for key, value in updates.items():
        row = db.get(AppSetting, key)
        if row:
            row.value = str(value)
        else:
            db.add(AppSetting(key=key, value=str(value)))
    db.commit()
    return _read(db)
