import os
from pathlib import Path


def delete_track_files(file_path: str, thumbnail_path: str | None = None) -> None:
    """Delete audio file, thumbnail, and .info.json sidecar."""
    for path in [file_path, thumbnail_path]:
        if path and os.path.exists(path):
            os.remove(path)

    # Remove .info.json sidecar if present
    p = Path(file_path)
    info_json = p.with_suffix("").with_suffix(".info.json")
    if info_json.exists():
        info_json.unlink()
