"""Runtime acceptance checks using the same adapter as production."""
import json
import subprocess
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yt_dlp

from app.services import ytdlp_service as service


def require(condition, message):
    if not condition:
        raise ValueError(message)


def entries_contract(entries):
    require(isinstance(entries, list) and bool(entries), "No video entries returned")
    for entry in entries:
        require(isinstance(entry.get("id"), str) and bool(entry["id"]), "Video ID contract changed")
        require(isinstance(entry.get("title"), str), "Video title contract changed")
        require(entry.get("url_type") in ("video", "playlist", "channel"), "URL type contract changed")


def validate(config, download_options=None):
    from yt_dlp.version import __version__
    results = validate_local()["checks"]
    video = service.resolve_url(config["video_url"])
    entries_contract(video)
    require(len(video) == 1 and video[0]["url_type"] == "video", "Test video must be a single video")
    results.append("video URL / metadata")
    entries_contract(service.resolve_url(config["playlist_url"]))
    playlist = service.get_playlist_info(config["playlist_url"])
    require(isinstance(playlist["playlist_id"], str) and bool(playlist["playlist_id"]), "Playlist ID missing")
    require(isinstance(playlist["playlist_title"], str), "Playlist title contract changed")
    require(bool(playlist["entries"]), "Test playlist is empty")
    for entry in playlist["entries"]:
        require(isinstance(entry["youtube_id"], str) and bool(entry["youtube_id"]), "Playlist video ID missing")
        require(isinstance(entry["title"], str), "Playlist title contract changed")
        require(isinstance(entry["position"], int), "Playlist position contract changed")
        require(entry["artist"] is None or isinstance(entry["artist"], str), "Artist contract changed")
        require(entry["duration_secs"] is None or isinstance(entry["duration_secs"], (int, float)), "Duration contract changed")
    results.append("playlist URL / entries")
    if config.get("channel_url"):
        entries_contract(service.resolve_url(config["channel_url"]))
        results.append("channel URL")

    # Bound network traffic by requiring a deliberately short reference video.
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True}) as ydl:
        info = ydl.extract_info(config["video_url"], download=False)
    require(not info.get("is_live") and isinstance(info.get("duration"), (int, float))
            and 0 < info["duration"] <= 60, "Test video must be a non-live video of at most 60 seconds")
    require(video[0]["id"] == info["id"], "Resolved video ID differs from extraction")
    options = download_options or {}
    with tempfile.TemporaryDirectory(prefix="ytdlp-probe-") as directory:
        for fmt in service.AUDIO_FORMATS + service.VIDEO_FORMATS:
            progress = []
            metadata = service.download_track(
                youtube_id=info["id"], audio_format=fmt, audio_quality="192",
                gain_percent=options.get("gain_percent", 10),
                silence_trim_start_secs=options.get("silence_trim_start_secs", 0.1),
                silence_trim_end_secs=options.get("silence_trim_end_secs", 0.1),
                ffmpeg_threads=options.get("ffmpeg_threads", 1),
                ffmpeg_memory_limit_mb=options.get("ffmpeg_memory_limit_mb", 0),
                ffmpeg_concurrent_processes=options.get("ffmpeg_concurrent_processes", 1),
                base_path=Path(directory) / fmt,
                progress_hook=progress.append,
            )
            path = Path(metadata["file_path"])
            require(path.is_file() and path.stat().st_size > 0, f"{fmt}: output missing or empty")
            require(metadata["file_size_bytes"] == path.stat().st_size, f"{fmt}: size contract changed")
            require(metadata["file_format"] == fmt and path.suffix == f".{fmt}", f"{fmt}: extension contract changed")
            require(isinstance(metadata["title"], str) and isinstance(metadata["artist"], str), f"{fmt}: metadata contract changed")
            require(metadata["youtube_id"] == info["id"], f"{fmt}: ID contract changed")
            require(any(p.get("status") == "finished" for p in progress), f"{fmt}: no finished progress event")
            for event in progress:
                if event.get("status") == "downloading":
                    require(isinstance(event.get("downloaded_bytes"), (int, float)), "Progress contract changed")
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                check=True, capture_output=True, text=True, timeout=30,
            )
            media = json.loads(probe.stdout)
            container_contract(media, fmt)
            streams = media["streams"]
            require(any(s["codec_type"] == "audio" for s in streams), f"{fmt}: no audio stream")
            if fmt in service.VIDEO_FORMATS:
                require(any(s["codec_type"] == "video" for s in streams), f"{fmt}: no video stream")
            codecs = {"mp3": "mp3", "flac": "flac", "aac": "aac", "ogg": "vorbis", "m4a": "aac"}
            if fmt in codecs:
                require(any(s.get("codec_name") == codecs[fmt] for s in streams), f"{fmt}: wrong audio codec")
            require(float(media["format"].get("duration", 0)) > 0, f"{fmt}: unreadable duration")
            results.append(f"{fmt}: download / conversion / file / progress")
    # Exception classes used by the production retry path must remain available.
    require(service._is_audio_postprocessing_error(yt_dlp.utils.PostProcessingError("probe")), "Postprocessing exception contract changed")
    return {"version": __version__, "checks": results}


def validate_local():
    """Exercise actual yt-dlp/FFmpeg APIs against a tiny generated local clip."""
    from yt_dlp.version import __version__
    results = []
    with tempfile.TemporaryDirectory(prefix="ytdlp-local-probe-") as directory:
        path = Path(directory)
        subprocess.run([
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=10",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "1",
            "-c:v", "libx264", "-c:a", "aac", "-threads", "1", str(path / "clip.mp4"),
        ], check=True, capture_output=True, timeout=30)
        subprocess.run([
            "ffmpeg", "-v", "error", "-i", str(path / "clip.mp4"), "-c:v", "libvpx-vp9",
            "-c:a", "libopus", "-threads", "1", str(path / "clip.webm"),
        ], check=True, capture_output=True, timeout=30)

        class Handler(SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=directory))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for fmt in service.AUDIO_FORMATS + service.VIDEO_FORMATS:
                progress = []
                opts = {
                    "quiet": True, "no_warnings": True,
                    "proxy": "",  # Local fixture traffic stays on loopback.
                    "format": service._format_selector(fmt),
                    "outtmpl": str(path / fmt / "%(title)s.%(ext)s"),
                    "postprocessors": service._postprocessors_for(fmt, "192"),
                    "postprocessor_args": service._download_postprocessor_args(fmt in service.VIDEO_FORMATS, 10, 0.1, 0.1, 1, audio_format=fmt),
                    "progress_hooks": [progress.append],
                    "noplaylist": True,
                }
                if fmt in service.VIDEO_FORMATS:
                    opts["merge_output_format"] = fmt
                if fmt == "aac":
                    opts["outtmpl"] = str(path / fmt / "%(title)s.aac-work.%(ext)s")
                with yt_dlp.YoutubeDL(opts) as ydl:
                    source = "clip.webm" if fmt == "webm" else "clip.mp4"
                    info = ydl.extract_info(f"http://127.0.0.1:{server.server_port}/{source}", download=True)
                output = path / fmt / f"{yt_dlp.utils.sanitize_filename(info['title'])}.{fmt}"
                if fmt == "aac":
                    output = service._normalize_aac_path(path / fmt, info["title"])
                require(output.is_file() and output.stat().st_size > 0, f"Local {fmt}: file naming or postprocessor contract changed")
                require(any(p.get("status") == "finished" for p in progress), f"Local {fmt}: progress contract changed")
                media = json.loads(subprocess.run(
                    ["ffprobe", "-v", "error", "-show_format", "-of", "json", str(output)],
                    check=True, capture_output=True, text=True, timeout=30,
                ).stdout)
                container_contract(media, fmt)
                results.append(f"local {fmt}: real yt-dlp / FFmpeg APIs")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
    return {"version": __version__, "checks": results}


def container_contract(media, fmt):
    containers = set(media["format"]["format_name"].split(","))
    expected = {"mp3": "mp3", "flac": "flac", "aac": "aac", "ogg": "ogg", "m4a": "m4a", "mp4": "mp4", "webm": "webm"}
    require(expected[fmt] in containers, f"{fmt}: actual container differs from requested format")
