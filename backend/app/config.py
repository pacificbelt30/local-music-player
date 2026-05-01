from pathlib import Path
from typing import Any
import json
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, SettingsConfigDict, EnvSettingsSource, DotEnvSettingsSource


class _CommaListMixin:
    """Allow comma-separated strings for list[str] fields (e.g. ALLOWED_ORIGINS=* or a,b,c)."""

    def prepare_field_value(
        self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool
    ) -> Any:
        if (
            value_is_complex
            and isinstance(value, str)
            and not value.startswith(("[", "{"))
        ):
            value = json.dumps([v.strip() for v in value.split(",") if v.strip()])
        return super().prepare_field_value(field_name, field, value, value_is_complex)


class _CommaEnvSource(_CommaListMixin, EnvSettingsSource):
    pass


class _CommaDotEnvSource(_CommaListMixin, DotEnvSettingsSource):
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:////home/user/local-music-player/data/music.db"
    redis_url: str = "redis://localhost:6379/0"
    redis_result_backend: str = "redis://localhost:6379/1"

    downloads_path: Path = Path("/home/user/local-music-player/downloads")
    data_path: Path = Path("/home/user/local-music-player/data")
    playlists_path: Path = Path("/home/user/local-music-player/playlists")

    syncthing_url: str = "http://localhost:8384"
    syncthing_api_key: str = ""

    allowed_origins: list[str] = ["*"]

    secret_token: str = ""  # Optional: set to require Bearer token auth

    # YouTube OAuth2 (Google Cloud Console credentials)
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_redirect_uri: str = "http://localhost:8000/api/v1/youtube/auth/callback"

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
