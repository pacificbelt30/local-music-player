import json
import shlex
import shutil
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

import yt_dlp

from app.config import settings


AUDIO_FORMATS = ("mp3", "flac", "aac", "ogg", "m4a")
VIDEO_FORMATS = ("mp4", "webm")


def _effective_ffmpeg_threads(ffmpeg_threads: int | None = None) -> int:
    return settings.ffmpeg_threads if ffmpeg_threads is None else ffmpeg_threads


def _ffmpeg_memory_preexec(memory_limit_mb: int | None = None):
    limit_mb = settings.ffmpeg_memory_limit_mb if memory_limit_mb is None else memory_limit_mb
    if limit_mb <= 0:
        return None

    def apply_limit() -> None:
        import resource

        limit_bytes = limit_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))

    return apply_limit


@contextmanager
def _limited_ffmpeg_location(memory_limit_mb: int | None = None) -> Iterator[str | None]:
    limit_mb = settings.ffmpeg_memory_limit_mb if memory_limit_mb is None else memory_limit_mb
    if limit_mb <= 0:
        yield None
        return

    real_ffmpeg = shutil.which("ffmpeg")
    if not real_ffmpeg:
        yield None
        return

    with tempfile.TemporaryDirectory(prefix="limited-ffmpeg-") as tmpdir:
        wrapper = Path(tmpdir) / "ffmpeg"
        wrapper.write_text(
            "#!/bin/sh\n"
            f"ulimit -v {limit_mb * 1024} || exit 125\n"
            f"exec {shlex.quote(real_ffmpeg)} \"$@\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        yield str(wrapper)


def is_video_format(audio_format: str) -> bool:
    return audio_format in VIDEO_FORMATS


def _postprocessors_for(audio_format: str, audio_quality: str) -> list[dict]:
    if audio_format in VIDEO_FORMATS:
        # Remux into the requested container when the merged download ends up
        # in a different one (note: yt-dlp spells the key "preferedformat").
        return [{"key": "FFmpegVideoRemuxer", "preferedformat": audio_format}]
    if audio_format == "mp3":
        return [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": audio_quality if audio_quality != "best" else "0"}]
    if audio_format == "flac":
        return [{"key": "FFmpegExtractAudio", "preferredcodec": "flac"}]
    if audio_format == "aac":
        return [{"key": "FFmpegExtractAudio", "preferredcodec": "aac"}]
    if audio_format == "ogg":
        return [{"key": "FFmpegExtractAudio", "preferredcodec": "vorbis"}]
    if audio_format == "m4a":
        return [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a"}]
    return [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]


def _silence_trim_filter(start_secs: float, end_secs: float, threshold_db: str = "-50dB") -> str | None:
    # start_periods=1 only ever matches the very first silence run, so reversing
    # the audio lets the same trick trim trailing silence without touching
    # silence elsewhere in the track.
    parts: list[str] = []
    if start_secs > 0:
        parts.append(
            f"silenceremove=start_periods=1:start_duration={start_secs}:"
            f"start_threshold={threshold_db}:detection=peak"
        )
    if end_secs > 0:
        parts.append("areverse")
        parts.append(
            f"silenceremove=start_periods=1:start_duration={end_secs}:"
            f"start_threshold={threshold_db}:detection=peak"
        )
        parts.append("areverse")
    return ",".join(parts) if parts else None


def _codec_args_for(audio_format: str) -> list[str]:
    if audio_format == "flac":
        return ["-codec:a", "flac"]
    if audio_format in ("aac", "m4a"):
        return ["-codec:a", "aac", "-b:a", "192k"]
    if audio_format == "ogg":
        return ["-codec:a", "libvorbis", "-q:a", "5"]
    return ["-codec:a", "libmp3lame", "-q:a", "2"]


def retrim_audio_file(
    file_path: str,
    audio_format: str,
    silence_trim_start_secs: float,
    silence_trim_end_secs: float,
    ffmpeg_threads: int | None = None,
    ffmpeg_memory_limit_mb: int | None = None,
) -> int | None:
    """Re-apply the silence-trim filter directly to an already-downloaded audio
    file in place, without redownloading from YouTube. Only safe when the trim
    seconds were decreased: the now-qualifying short silence is still physically
    present at the edges of the local file, since the previous (larger) setting
    never removed it. Returns the new file size, or None if nothing was done.
    """
    trim_filter = _silence_trim_filter(silence_trim_start_secs, silence_trim_end_secs)
    if not trim_filter or audio_format in VIDEO_FORMATS:
        return None

    path = Path(file_path)
    if not path.exists():
        return None

    tmp_path = path.with_suffix(f".trim{path.suffix}")
    effective_threads = _effective_ffmpeg_threads(ffmpeg_threads)
    cmd = [
        "ffmpeg", "-y", "-i", str(path),
        "-threads", str(effective_threads if effective_threads >= 0 else 0),
        "-af", trim_filter,
        *_codec_args_for(audio_format),
        str(tmp_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, preexec_fn=_ffmpeg_memory_preexec(ffmpeg_memory_limit_mb))
    except subprocess.CalledProcessError:
        tmp_path.unlink(missing_ok=True)
        raise
    tmp_path.replace(path)
    return path.stat().st_size


def _format_selector(audio_format: str) -> str:
    if audio_format in VIDEO_FORMATS:
        return f"bestvideo[ext={audio_format}]+bestaudio/bestvideo+bestaudio/best"
    return "bestaudio/best"


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
    silence_trim_start_secs: float = 0.0,
    silence_trim_end_secs: float = 0.0,
    progress_hook: Callable[[dict], None] | None = None,
    base_path: Path | None = None,
    ffmpeg_threads: int | None = None,
    ffmpeg_memory_limit_mb: int | None = None,
) -> dict[str, Any]:
    """Download a single track. Returns metadata dict on success."""
    dest = base_path or settings.downloads_path
    dest.mkdir(parents=True, exist_ok=True)
    output_template = str(dest / "%(title)s.%(ext)s")

    is_video = is_video_format(audio_format)
    ydl_opts: dict[str, Any] = {
        "format": _format_selector(audio_format),
        "outtmpl": output_template,
        "postprocessors": _postprocessors_for(audio_format, audio_quality),
        "writeinfojson": False,
        "writethumbnail": False,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    if is_video:
        ydl_opts["merge_output_format"] = audio_format

    ffmpeg_args: list[str] = []
    effective_threads = _effective_ffmpeg_threads(ffmpeg_threads)
    if effective_threads >= 0:
        ffmpeg_args.extend(["-threads", str(effective_threads)])

    # Video downloads are stream-copied (no re-encode), so audio filters
    # cannot be applied there.
    audio_filters: list[str] = []
    if not is_video:
        if gain_percent > 0:
            audio_filters.append(f"volume={1 + (gain_percent / 100):.4f}")
        trim_filter = _silence_trim_filter(silence_trim_start_secs, silence_trim_end_secs)
        if trim_filter:
            audio_filters.append(trim_filter)

    if audio_filters:
        ffmpeg_args.extend(["-af", ",".join(audio_filters)])

    if ffmpeg_args:
        ydl_opts["postprocessor_args"] = ffmpeg_args


    if progress_hook:
        ydl_opts["progress_hooks"] = [progress_hook]

    with _limited_ffmpeg_location(ffmpeg_memory_limit_mb) as ffmpeg_location:
        if ffmpeg_location:
            ydl_opts["ffmpeg_location"] = ffmpeg_location
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={youtube_id}", download=True)

    # Determine the actual downloaded file path
    ext = audio_format if audio_format in AUDIO_FORMATS + VIDEO_FORMATS else "mp3"
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
