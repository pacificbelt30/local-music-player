"""Execute each request against one immutable yt-dlp installation."""
import json
import os
import queue
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import yt_dlp

BACKEND = Path(__file__).resolve().parents[2]


def _stop(process):
    # Include ffmpeg descendants, including after the Python process exits.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def call(operation, arguments, *, installation=None, timeout=3600, progress_hook=None):
    if installation is None:
        from app.services.ytdlp_updates import active_installation
        installation = active_installation()
    env = os.environ.copy()
    paths = [str(BACKEND)]
    if installation.get("path"):
        paths.insert(0, installation["path"])
    env.update(PYTHONPATH=os.pathsep.join(paths), YTDLP_CHILD="1", PYTHONUNBUFFERED="1")
    # Disk-backed stderr avoids a full pipe blocking a download.
    with tempfile.TemporaryFile(mode="w+b") as errors:
        process = subprocess.Popen(
            [sys.executable, "-P", "-m", "app.services.ytdlp_runner"],
            cwd=BACKEND, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=errors, text=True, start_new_session=True,
        )
        messages = queue.Queue(maxsize=128)
        stopped = threading.Event()

        def read_messages():
            try:
                for line in process.stdout:
                    while not stopped.is_set():
                        try:
                            messages.put(line, timeout=0.1)
                            break
                        except queue.Full:
                            continue
                    if stopped.is_set():
                        return
                while not stopped.is_set():
                    try:
                        messages.put(None, timeout=0.1)
                        break
                    except queue.Full:
                        continue
            except (ValueError, OSError):
                pass

        reader = threading.Thread(target=read_messages, daemon=True)
        reader.start()
        deadline = time.monotonic() + timeout
        result = None
        try:
            process.stdin.write(json.dumps({"operation": operation, "arguments": arguments}, default=str) + "\n")
            process.stdin.close()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"yt-dlp {operation} timed out")
                try:
                    line = messages.get(timeout=remaining)
                except queue.Empty:
                    raise TimeoutError(f"yt-dlp {operation} timed out") from None
                if line is None:
                    break
                message = json.loads(line)
                if message["type"] == "progress" and progress_hook:
                    progress_hook(message["data"])
                elif message["type"] == "result":
                    result = message
                elif message["type"] == "error":
                    error_types = {
                        "DownloadError": yt_dlp.utils.DownloadError,
                        "PostProcessingError": yt_dlp.utils.PostProcessingError,
                        "ValueError": ValueError,
                    }
                    raise error_types.get(message["error_type"], RuntimeError)(message["message"])
            code = process.wait(timeout=max(0.01, deadline - time.monotonic()))
            if code or result is None:
                errors.seek(0, 2)
                errors.seek(max(0, errors.tell() - 4000))
                raise RuntimeError(errors.read().decode(errors="replace") or "yt-dlp process returned no result")
            return result["data"]
        finally:
            stopped.set()
            _stop(process)
            reader.join(timeout=2)
            process.stdout.close()

