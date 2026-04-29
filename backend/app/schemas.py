from datetime import datetime
from typing import Literal
from pydantic import BaseModel, HttpUrl, field_validator


AudioFormat = Literal["mp3", "flac", "aac", "ogg"]
AudioQuality = Literal["best", "192", "320"]
JobStatus = Literal["pending", "downloading", "complete", "failed", "skipped"]


class UrlSourceCreate(BaseModel):
    url: str
    audio_format: AudioFormat = "mp3"
    audio_quality: AudioQuality = "192"
    sync_enabled: bool = True

    @field_validator("url")
    @classmethod
    def url_must_be_youtube(cls, v: str) -> str:
        if "youtube.com" not in v and "youtu.be" not in v:
            raise ValueError("URL must be a YouTube URL")
        return v


class UrlSourceResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    url: str
    url_type: str
    audio_format: str
    audio_quality: str
    title: str | None
    added_at: datetime
    last_synced: datetime | None
    sync_enabled: bool


class DownloadJobResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    url_source_id: int | None
    youtube_id: str
    status: str
    progress_pct: float
    celery_task_id: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class TrackResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    youtube_id: str
    title: str
    artist: str | None
    album: str | None
    duration_secs: int | None
    file_format: str | None
    file_size_bytes: int | None
    thumbnail_url: str | None = None
    stream_url: str | None = None
    download_url: str | None = None
    added_at: datetime
    last_played_at: datetime | None
    play_count: int


class TrackUpdate(BaseModel):
    title: str | None = None
    artist: str | None = None
    album: str | None = None


class HealthResponse(BaseModel):
    status: str
    redis_connected: bool
    db_ok: bool
    worker_active: bool
