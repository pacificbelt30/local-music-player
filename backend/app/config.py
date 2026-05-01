from pathlib import Path
from typing import Any
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, SettingsConfigDict, EnvSettingsSource, DotEnvSettingsSource


class _CommaListMixin:
    """Parse comma-separated env strings (e.g. ALLOWED_ORIGINS=*) into list[str]."""

    def decode_complex_value(self, field_name: str, field: FieldInfo, value: Any) -> Any:
        if isinstance(value, str) and not value.startswith(("[", "{")):
            return [v.strip() for v in value.split(",") if v.strip()]
        return super().decode_complex_value(field_name, field, value)


class _CommaEnvSource(_CommaListMixin, EnvSettingsSource):
    pass


class _CommaDotEnvSource(_CommaListMixin, DotEnvSettingsSource):
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:////home/user/SyncTuneHub/data/music.db"
    redis_url: str = "redis://localhost:6379/0"
    redis_result_backend: str = "redis://localhost:6379/1"

    downloads_path: Path = Path("/home/user/SyncTuneHub/downloads")
    data_path: Path = Path("/home/user/SyncTuneHub/data")
    playlists_path: Path = Path("/home/user/SyncTuneHub/playlists")

    syncthing_url: str = "http://localhost:8384"
    syncthing_api_key: str = ""
    syncthing_gui_user: str = ""
    syncthing_gui_password: str = ""

    allowed_origins: list[str] = ["*"]

    secret_token: str = ""  # Optional: set to require Bearer token auth

    # YouTube OAuth2 (Google Cloud Console credentials)
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_redirect_uri: str = "http://localhost:8000/api/v1/youtube/auth/callback"

    # ffmpeg/yt-dlp resource controls
    ffmpeg_threads: int = 1  # 1 keeps CPU usage predictable; set 0 for ffmpeg default(auto)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        return (
            init_settings,
            _CommaEnvSource(settings_cls),
            _CommaDotEnvSource(settings_cls),
            file_secret_settings,
        )


settings = Settings()
