from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class UrlSource(Base):
    __tablename__ = "url_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    url_type: Mapped[str] = mapped_column(String(20), nullable=False)  # video/playlist/channel
    audio_format: Mapped[str] = mapped_column(String(10), default="mp3")  # mp3/flac/aac/ogg
    audio_quality: Mapped[str] = mapped_column(String(10), default="192")  # best/192/320
    title: Mapped[str | None] = mapped_column(Text)
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_synced: Mapped[datetime | None] = mapped_column(DateTime)
    sync_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    jobs: Mapped[list["DownloadJob"]] = relationship(back_populates="url_source", cascade="all, delete-orphan")
    playlist_tracks: Mapped[list["PlaylistTrack"]] = relationship(back_populates="url_source", cascade="all, delete-orphan")


class DownloadJob(Base):
    __tablename__ = "download_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url_source_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("url_sources.id", ondelete="CASCADE"))
    youtube_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/downloading/complete/failed/skipped
    progress_pct: Mapped[float] = mapped_column(Float, default=0.0)
    celery_task_id: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    url_source: Mapped["UrlSource | None"] = relationship(back_populates="jobs")


class Track(Base):
    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    youtube_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    artist: Mapped[str | None] = mapped_column(Text)
    album: Mapped[str | None] = mapped_column(Text)
    duration_secs: Mapped[int | None] = mapped_column(Integer)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_format: Mapped[str | None] = mapped_column(String(10))
    file_size_bytes: Mapped[int | None] = mapped_column(Integer)
    thumbnail_path: Mapped[str | None] = mapped_column(Text)
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_played_at: Mapped[datetime | None] = mapped_column(DateTime)
    play_count: Mapped[int] = mapped_column(Integer, default=0)

    playlist_tracks: Mapped[list["PlaylistTrack"]] = relationship(back_populates="track", cascade="all, delete-orphan")


class PlaylistTrack(Base):
    __tablename__ = "playlist_tracks"
    __table_args__ = (UniqueConstraint("url_source_id", "track_id"),)

    url_source_id: Mapped[int] = mapped_column(Integer, ForeignKey("url_sources.id", ondelete="CASCADE"), primary_key=True)
    track_id: Mapped[int] = mapped_column(Integer, ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int | None] = mapped_column(Integer)

    url_source: Mapped["UrlSource"] = relationship(back_populates="playlist_tracks")
    track: Mapped["Track"] = relationship(back_populates="playlist_tracks")
