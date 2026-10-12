"""One-request JSON-lines worker; stdout is reserved for the protocol."""
import contextlib
import json
import sys
from pathlib import Path


def emit(kind, **values):
    sys.__stdout__.write(json.dumps({"type": kind, **values}, ensure_ascii=False) + "\n")
    sys.__stdout__.flush()


def main():
    try:
        request = json.loads(sys.stdin.readline())
        with contextlib.redirect_stdout(sys.stderr):
            from app.services import ytdlp_service
            operation = request["operation"]
            args = request["arguments"]
            if operation == "probe":
                from app.services.ytdlp_probe import validate
                result = validate(**args)
            elif operation == "local_probe":
                from app.services.ytdlp_probe import validate_local
                result = validate_local()
            elif operation in ("resolve_url", "get_playlist_info", "download_track"):
                if args.get("base_path"):
                    args["base_path"] = Path(args["base_path"])
                if operation == "download_track":
                    def progress(d):
                        data = {k: d[k] for k in ("status", "total_bytes", "total_bytes_estimate", "downloaded_bytes") if k in d}
                        emit("progress", data=data)
                    args["progress_hook"] = progress
                result = getattr(ytdlp_service, operation)(**args)
            else:
                raise ValueError("Unknown yt-dlp operation")
        emit("result", data=result)
    except Exception as exc:
        emit("error", error_type=type(exc).__name__, message=str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
