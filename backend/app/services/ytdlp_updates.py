"""Persistent, locked updater. Installations are immutable once selected."""
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, Field, field_validator
from yt_dlp.version import __version__

from app.config import settings


class UpdateConfig(BaseModel):
    enabled: bool = True
    interval_minutes: int = Field(default=1440, ge=60, le=10080)
    video_url: str = ""
    playlist_url: str = ""
    channel_url: str = ""

    @field_validator("video_url", "playlist_url", "channel_url")
    @classmethod
    def youtube_url(cls, value, info):
        value = value.strip()
        if not value:
            return value
        url = urlsplit(value)
        if (url.scheme != "https" or url.hostname not in ("youtube.com", "www.youtube.com", "youtu.be")
                or url.username or url.password or url.port not in (None, 443)):
            raise ValueError("Use a public HTTPS YouTube URL")
        query = parse_qs(url.query)
        if info.field_name == "playlist_url" and (url.path != "/playlist" or not query.get("list")):
            raise ValueError("Use a YouTube playlist URL")
        if info.field_name == "video_url":
            if query.get("list") or not (url.hostname == "youtu.be" and url.path.strip("/")
                                        or url.path == "/watch" and query.get("v")
                                        or url.path.startswith("/shorts/")):
                raise ValueError("Use a single YouTube video URL without a playlist")
        if info.field_name == "channel_url" and not url.path.startswith(("/@", "/channel/", "/c/", "/user/")):
            raise ValueError("Use a YouTube channel URL")
        return value


class UpdateBusy(RuntimeError):
    pass


def root():
    return settings.data_path / "ytdlp-runtime"


def bundled():
    return {"version": __version__, "path": None}


def read_state():
    try:
        state = json.loads((root() / "state.json").read_text())
    except FileNotFoundError:
        state = {}
    # Refresh the bundled version after an application image upgrade.
    if not state.get("active", {}).get("path"):
        state["active"] = bundled()
    if state.get("previous") is not None and not state["previous"].get("path"):
        state["previous"] = bundled()
    state.setdefault("config", UpdateConfig().model_dump())
    state.setdefault("status", "idle")
    state.setdefault("previous", None)
    return state


def save_state(state):
    directory = root()
    directory.mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix="state-", dir=directory)
    try:
        with os.fdopen(fd, "w") as file:
            json.dump(state, file, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(path, directory / "state.json")
    finally:
        Path(path).unlink(missing_ok=True)


@contextmanager
def mutation_lock():
    root().mkdir(parents=True, exist_ok=True)
    with (root() / "update.lock").open("a") as file:
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise UpdateBusy("更新処理が実行中です") from None
        try:
            yield
        finally:
            fcntl.flock(file, fcntl.LOCK_UN)


def active_installation():
    return read_state()["active"]


def status():
    state = read_state()
    busy = False
    try:
        with mutation_lock():
            state = read_state()
            # A worker crash releases the OS lock; do not leave a misleading spinner.
            if state["status"] in ("checking", "installing", "testing"):
                state.update(status="interrupted", error="更新処理が中断されました。現行版を維持しています")
                save_state(state)
    except UpdateBusy:
        busy = True
    return {**state, "busy": busy}


def configure(config):
    with mutation_lock():
        state = read_state()
        state["config"] = config.model_dump()
        # A corrected test URL should not wait another full interval.
        state["last_checked_at"] = None
        save_state(state)
    return state


def rollback():
    with mutation_lock():
        state = read_state()
        if state["previous"] is None:
            raise ValueError("切り戻せるバージョンがありません")
        state["active"], state["previous"] = state["previous"], state["active"]
        state["config"]["enabled"] = False
        state.update(status="rolled_back", error=None)
        save_state(state)
    return state


def latest_version():
    with urllib.request.urlopen("https://pypi.org/pypi/yt-dlp/json", timeout=30) as response:
        # Release history makes this response larger than 1 MiB.
        maximum = 16 * 1024 * 1024
        payload = response.read(maximum + 1)
        if len(payload) > maximum:
            raise ValueError("PyPI metadata exceeds the maximum size")
        version = json.loads(payload)["info"]["version"]
    version_key(version)
    return version


def version_key(version):
    if not re.fullmatch(r"\d{4}\.\d{1,2}\.\d{1,2}", version):
        raise ValueError("Unexpected yt-dlp release version")
    return tuple(map(int, version.split(".")))


def install(version):
    version_key(version)
    directory = root() / "installations" / f"{version}-{uuid.uuid4().hex}"
    directory.mkdir(parents=True)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "--isolated", "install", "--no-cache-dir",
             "--disable-pip-version-check", "--only-binary=:all:", "--index-url", "https://pypi.org/simple",
             "--target", str(directory), f"yt-dlp[default]=={version}"],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode:
            raise RuntimeError(result.stderr[-4000:] or "Installation failed")
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    return {"version": version, "path": str(directory)}


def download_options():
    from app.database import SessionLocal
    from app.models import AppSetting
    from app.tasks.scheduler import DEFAULTS
    mapping = {
        "gain_percent": ("download_gain_percent", float),
        "silence_trim_start_secs": ("silence_trim_start_secs", float),
        "silence_trim_end_secs": ("silence_trim_end_secs", float),
        "ffmpeg_threads": ("ffmpeg_threads", int),
        "ffmpeg_memory_limit_mb": ("ffmpeg_memory_limit_mb", int),
        "ffmpeg_concurrent_processes": ("celery_worker_concurrency", int),
    }
    with SessionLocal() as db:
        options = {}
        for name, (key, convert) in mapping.items():
            row = db.get(AppSetting, key)
            options[name] = convert(row.value if row else DEFAULTS[key])
    return options


def run_probe(installation, config, options):
    from app.services.ytdlp_process import call
    try:
        result = call("probe", {"config": config, "download_options": options}, installation=installation, timeout=900)
        if version_key(result["version"]) != version_key(installation["version"]):
            raise ValueError("Loaded yt-dlp version differs from the selected version")
        return {"passed": True, **result}
    except Exception as exc:
        return {"passed": False, "version": installation["version"], "error": str(exc)[-4000:]}


def check(*, force=False):
    try:
        with mutation_lock():
            state = read_state()
            config = UpdateConfig(**state["config"])
            now = datetime.now(timezone.utc)
            if not force:
                if not config.enabled:
                    return state
                last = state.get("last_checked_at")
                if last and (now - datetime.fromisoformat(last)).total_seconds() < config.interval_minutes * 60:
                    return state
            state.update(last_checked_at=now.isoformat(), status="checking", error=None, tests=None, candidate=None)
            save_state(state)
            candidate = None
            try:
                version = latest_version()
                state["latest_version"] = version
                if version_key(version) <= version_key(state["active"]["version"]):
                    state["status"] = "up_to_date"
                elif not config.video_url or not config.playlist_url:
                    state.update(status="needs_configuration", error="60秒以内の検証用動画と公開プレイリストを設定してください")
                else:
                    state.update(status="installing", candidate={"version": version})
                    save_state(state)
                    candidate = install(version)
                    state.update(status="testing", candidate=candidate)
                    save_state(state)
                    options = download_options()
                    baseline = run_probe(state["active"], config.model_dump(), options)
                    state["tests"] = {"current": baseline}
                    save_state(state)
                    tested = run_probe(candidate, config.model_dump(), options)
                    state["tests"]["candidate"] = tested
                    if tested["passed"]:
                        state["previous"] = state["active"]
                        state["active"] = candidate
                        state.update(status="updated", updated_at=datetime.now(timezone.utc).isoformat())
                    else:
                        state.update(status="rejected" if baseline["passed"] else "inconclusive", error=tested["error"])
                        shutil.rmtree(candidate["path"], ignore_errors=True)
                        state["candidate"] = {"version": version}
            except Exception as exc:
                state.update(status="failed", error=str(exc)[-4000:])
                if candidate and candidate != state["active"]:
                    shutil.rmtree(candidate["path"], ignore_errors=True)
            save_state(state)
            return state
    except UpdateBusy:
        return {**read_state(), "busy": True}
