from datetime import datetime
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlparse
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


# Query params that don't affect which video/playlist/channel a URL points
# at (share-link tracking, timestamps, etc.) — ignored when deduping.
_TRACKING_PARAMS = {"si", "feature", "pp", "ab_channel", "t", "time_continue", "app"}


def normalize_youtube_url(v: str) -> str:
    """Canonical dedupe key for a YouTube URL.

    Treats scheme, host casing/subdomain (www./m./music.), trailing slashes,
    query-param order, and tracking params as insignificant, and resolves
    youtu.be / shorts / embed / live links to the same key as the equivalent
    watch?v= URL so that visually different URLs pointing at the same video,
    playlist, or channel collide.
    """
    parsed = urlparse(v)
    host = (parsed.hostname or "").lower().rstrip(".")
    path = parsed.path.rstrip("/")
    query = dict(parse_qsl(parsed.query))

    if host == "youtu.be":
        video_id = path.lstrip("/").split("/")[0]
        if video_id:
            return f"video:{video_id}"
    else:
        segments = [s for s in path.split("/") if s]
        segments_lower = [s.lower() for s in segments]
        if segments_lower and segments_lower[0] in ("shorts", "embed", "live") and len(segments) > 1:
            return f"video:{segments[1]}"
        if segments_lower and segments_lower[0] == "watch" and query.get("v"):
            return f"video:{query['v']}"
        if segments_lower and segments_lower[0] == "playlist" and query.get("list"):
            return f"playlist:{query['list']}"
        if segments_lower and segments_lower[0] == "channel" and len(segments) > 1:
            return f"channel:{segments[1]}"
        if segments_lower and segments_lower[0] in ("c", "user") and len(segments) > 1:
            return f"channel:{segments_lower[0]}/{segments[1]}"
        if segments and segments[0].startswith("@"):
            return f"channel:{segments[0].lower()}"

    # Fallback for anything not recognized above: normalize host/path and
    # drop tracking params, but otherwise compare the full URL.
    normalized_host = host[4:] if host.startswith("www.") else host
    kept_query = sorted((k, val) for k, val in parse_qsl(parsed.query) if k not in _TRACKING_PARAMS)
    query_str = urlencode(kept_query)
    return f"url:{normalized_host}{path}?{query_str}" if query_str else f"url:{normalized_host}{path}"


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


# ── Debug / Monitoring ─────────────────────────────────────────────────────────

class ActiveTaskDetail(BaseModel):
    task_id: str
    name: str
    args: str
    kwargs: str
    time_start: float | None = None


class WorkerInfo(BaseModel):
    name: str
    active_tasks: int
    concurrency: int | None = None
    active_task_names: list[str] = []
    active_tasks_detail: list[ActiveTaskDetail] = []
    reserved_tasks: int = 0
    scheduled_tasks: int = 0


class RecentJobInfo(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    youtube_id: str
    title: str | None
    status: str
    error_message: str | None
    celery_task_id: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class QueueStats(BaseModel):
    pending: int
    downloading: int
    complete: int
    failed: int
    skipped: int
    total: int
    stuck: int
    recent_jobs: list[RecentJobInfo] = []


class OAuthDebugInfo(BaseModel):
    authenticated: bool
    token_expiry: datetime | None = None
    expires_in_seconds: int | None = None
    scope: str | None = None
    is_expired: bool = False
    needs_refresh: bool = False
    access_token_preview: str | None = None
    refresh_token_set: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RedisInfo(BaseModel):
    connected: bool
    used_memory_human: str | None = None
    connected_clients: int | None = None
    uptime_in_seconds: int | None = None
    total_commands_processed: int | None = None
    raw: dict[str, object] | None = None


class DBStats(BaseModel):
    tracks: int
    download_jobs: int
    url_sources: int
    youtube_syncs: int
    playlist_sync_tracks: int


class BeatTaskInfo(BaseModel):
    name: str
    schedule: str


class DiskUsageInfo(BaseModel):
    label: str
    path: str
    total_bytes: int
    used_bytes: int
    free_bytes: int


class SyncErrorInfo(BaseModel):
    id: int
    playlist_name: str
    last_error: str
    last_synced: datetime | None


class AppInfo(BaseModel):
    version: str
    started_at: datetime
    uptime_seconds: float


class DebugResponse(BaseModel):
    server_time: datetime
    workers: list[WorkerInfo]
    worker_count: int
    queue: QueueStats
    oauth: OAuthDebugInfo
    redis: RedisInfo
    db: DBStats
    beat_schedule: list[BeatTaskInfo]
    disk_usage: list[DiskUsageInfo]
    sync_errors: list[SyncErrorInfo]
    app_info: AppInfo


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
