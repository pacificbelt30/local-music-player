from datetime import datetime
from typing import Literal
from urllib.parse import urlparse
from pydantic import BaseModel, HttpUrl, field_validator, model_validator


# "audio_format" fields also accept video containers (mp4/webm); the name is
# kept for API/DB compatibility.
MediaFormat = Literal["mp3", "flac", "aac", "ogg", "m4a", "mp4", "webm"]
AudioQuality = Literal["best", "192", "320"]
JobStatus = Literal["pending", "downloading", "complete", "failed", "skipped"]

_YOUTUBE_HOSTS = {"youtube.com", "youtu.be"}


def _is_youtube_url(v: str) -> bool:
    """True if v is an http(s) URL whose host is youtube.com/youtu.be or a
    subdomain of youtube.com (www./m./music./etc). Validates the actual host
    rather than checking for a substring, which a URL like
    "https://evil.example/?x=youtube.com" would otherwise satisfy.
    """
    try:
        parsed = urlparse(v)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return False
    return host in _YOUTUBE_HOSTS or host.endswith(".youtube.com")


class UrlSourceCreate(BaseModel):
    url: str
    audio_format: MediaFormat = "mp3"
    audio_quality: AudioQuality = "192"
    sync_enabled: bool = True

    @field_validator("url")
    @classmethod
    def url_must_be_youtube(cls, v: str) -> str:
        if not _is_youtube_url(v):
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
    title: str | None
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


# ── YouTube Playlist Sync ──────────────────────────────────────────────────────

class YouTubeAuthStatus(BaseModel):
    authenticated: bool
    scope: str | None = None


class YouTubeTokenInput(BaseModel):
    access_token: str
    refresh_token: str = ""
    expires_in: int = 3600


class YouTubePlaylistInfo(BaseModel):
    playlist_id: str
    title: str
    item_count: int
    thumbnail_url: str | None = None
    total_duration_secs: int | None = None
    # "private" | "unlisted" | "public" | None (older readonly tokens)
    privacy_status: str | None = None


class PlaylistPrivacyUpdate(BaseModel):
    privacy_status: Literal["private", "unlisted", "public"] = "unlisted"


class YoutubePlaylistSyncCreate(BaseModel):
    # API方式用
    playlist_id: str = ""
    playlist_name: str = ""
    # URL方式用
    source_type: Literal["api", "url"] = "api"
    source_url: str = ""
    audio_format: MediaFormat = "mp3"
    audio_quality: AudioQuality = "192"
    enabled: bool = True

    @model_validator(mode="after")
    def source_url_must_be_youtube(self):
        if self.source_type == "url":
            if not _is_youtube_url(self.source_url):
                raise ValueError("source_url must be a YouTube URL")
        return self


class YoutubePlaylistSyncUpdate(BaseModel):
    audio_format: MediaFormat | None = None
    audio_quality: AudioQuality | None = None
    enabled: bool | None = None


class YoutubePlaylistSyncResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    playlist_id: str
    playlist_name: str
    source_type: str = "api"
    source_url: str = ""
    audio_format: str
    audio_quality: str
    enabled: bool
    last_synced: datetime | None
    created_at: datetime
    track_count: int = 0
    downloaded_count: int = 0
    last_error: str | None = None


class PlaylistSyncTrackResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    youtube_id: str
    title: str
    artist: str | None
    duration_secs: int | None
    position: int | None
    status: str
    thumbnail_url: str | None = None
    stream_url: str | None = None
    error_message: str | None
    added_at: datetime
    downloaded_at: datetime | None
