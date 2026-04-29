from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


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


settings = Settings()
