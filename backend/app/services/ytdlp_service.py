import json
import subprocess
from pathlib import Path
from typing import Any, Callable

import yt_dlp

from app.config import settings


def _postprocessors_for(audio_format: str, audio_quality: str) -> list[dict]:
    if audio_format == "mp3":
        return [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": audio_quality if audio_quality != "best" else "0"}]
    if audio_format == "flac":
        return [{"key": "FFmpegExtractAudio", "preferredcodec": "flac"}]
    if audio_format == "aac":
        return [{"key": "FFmpegExtractAudio", "preferredcodec": "aac"}]
    if audio_format == "ogg":
        return [{"key": "FFmpegExtractAudio", "preferredcodec": "vorbis"}]
    return [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]


def get_playlist_info(url: str) -> dict:
    """Fetch playlist metadata and all entries without downloading."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "dump_single_json": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if info.get("_type") not in ("playlist", "channel"):
        raise ValueError("URL must be a YouTube playlist")

    entries = []
    for i, entry in enumerate(info.get("entries") or []):
        if not entry or not entry.get("id"):
            continue
        thumbnails = entry.get("thumbnails") or []
        thumbnail_url = thumbnails[-1].get("url") if thumbnails else None
        entries.append({
            "youtube_id": entry["id"],
            "title": entry.get("title", "Unknown"),
            "artist": entry.get("uploader") or entry.get("channel"),
            "duration_secs": entry.get("duration"),
            "position": entry.get("playlist_index", i + 1),
            "thumbnail_url": thumbnail_url,
        })

    return {
        "playlist_id": info.get("id", ""),
        "playlist_title": info.get("title", ""),
        "entries": entries,
    }


def resolve_url(url: str) -> list[dict[str, Any]]:
    """Return a flat list of {id, title, url_type} dicts without downloading."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "dump_single_json": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    entries = []
    url_type = "video"

    if info.get("_type") in ("playlist", "channel"):
        url_type = info.get("_type", "playlist")
        for entry in info.get("entries", []):
            if entry and entry.get("id"):
                entries.append({
                    "id": entry["id"],
                    "title": entry.get("title", "Unknown"),
                    "url_type": url_type,
                    "playlist_title": info.get("title"),
                })
    else:
        entries.append({
            "id": info["id"],
            "title": info.get("title", "Unknown"),
            "url_type": "video",
            "playlist_title": None,
        })

    return entries


def download_track(
    youtube_id: str,
    audio_format: str,
    audio_quality: str,
    gain_percent: float,
    progress_hook: Callable[[dict], None] | None = None,
    base_path: Path | None = None,
) -> dict[str, Any]:
    """Download a single track. Returns metadata dict on success."""
    dest = base_path or settings.downloads_path
    dest.mkdir(parents=True, exist_ok=True)
    output_template = str(dest / "%(title)s.%(ext)s")

    ydl_opts: dict[str, Any] = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "postprocessors": _postprocessors_for(audio_format, audio_quality),
        "writeinfojson": False,
        "writethumbnail": False,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }

    ffmpeg_args: list[str] = []
    if settings.ffmpeg_threads >= 0:
        ffmpeg_args.extend(["-threads", str(settings.ffmpeg_threads)])

    if gain_percent > 0:
        ffmpeg_args.extend(["-af", f"volume={1 + (gain_percent / 100):.4f}"])

    if ffmpeg_args:
        ydl_opts["postprocessor_args"] = ffmpeg_args


    if progress_hook:
        ydl_opts["progress_hooks"] = [progress_hook]

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={youtube_id}", download=True)

    # Determine the actual downloaded file path
    ext = audio_format if audio_format in ("mp3", "flac", "aac", "ogg") else "mp3"
    uploader = info.get("uploader") or info.get("channel") or "Unknown"
    title = info.get("title", youtube_id)

    # Sanitize filename the same way yt-dlp does
    safe_title = yt_dlp.utils.sanitize_filename(title)
    file_path = dest / f"{safe_title}.{ext}"

    return {
        "youtube_id": youtube_id,
        "title": title,
        "artist": uploader,
        "album": info.get("playlist_title"),
        "duration_secs": info.get("duration"),
        "file_path": str(file_path),
        "file_format": ext,
        "file_size_bytes": file_path.stat().st_size if file_path.exists() else None,
        "thumbnail_path": None,
    }
