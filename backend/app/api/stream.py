import os
from datetime import datetime, timezone
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Track

router = APIRouter(tags=["stream"])

CHUNK_SIZE = 1024 * 1024  # 1 MB


async def _range_response(file_path: str, request: Request, filename: str | None = None) -> Response:
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    file_size = os.path.getsize(file_path)
    range_header = request.headers.get("range")

    ext = Path(file_path).suffix.lower()
    content_type_map = {
        ".mp3": "audio/mpeg",
        ".flac": "audio/flac",
        ".aac": "audio/aac",
        ".ogg": "audio/ogg",
        ".m4a": "audio/mp4",
    }
    content_type = content_type_map.get(ext, "audio/mpeg")

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Cache-Control": "public, max-age=3600",
    }

    if filename:
        safe_name = filename.replace('"', "'")
        headers["Content-Disposition"] = f'attachment; filename="{safe_name}"'

    if range_header:
        start, end = range_header.replace("bytes=", "").split("-")
        start = int(start)
        end = int(end) if end else file_size - 1
        end = min(end, file_size - 1)
        content_length = end - start + 1

        async def generate():
            async with aiofiles.open(file_path, "rb") as f:
                await f.seek(start)
                remaining = content_length
                while remaining > 0:
                    chunk = await f.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        headers["Content-Length"] = str(content_length)
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        return StreamingResponse(generate(), status_code=206, media_type=content_type, headers=headers)

    async def generate_full():
        async with aiofiles.open(file_path, "rb") as f:
            while chunk := await f.read(CHUNK_SIZE):
                yield chunk

    return StreamingResponse(generate_full(), status_code=200, media_type=content_type, headers=headers)


@router.get("/stream/{track_id}")
async def stream_track(track_id: int, request: Request, db: Session = Depends(get_db)):
    track = db.get(Track, track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    # Increment play count
    track.play_count += 1
    track.last_played_at = datetime.now(timezone.utc)
    db.commit()

    return await _range_response(track.file_path, request)


@router.get("/thumbnails/{track_id}")
async def get_thumbnail(track_id: int, db: Session = Depends(get_db)):
    track = db.get(Track, track_id)
    if not track or not track.thumbnail_path:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    if not os.path.exists(track.thumbnail_path):
        raise HTTPException(status_code=404, detail="Thumbnail file not found on disk")

    ext = Path(track.thumbnail_path).suffix.lower()
    content_type = {"jpg": "image/jpeg", ".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(ext, "image/jpeg")
    return FileResponse(track.thumbnail_path, media_type=content_type, headers={"Cache-Control": "public, max-age=86400"})


@router.get("/files/{track_id}/download")
async def download_file(track_id: int, request: Request, db: Session = Depends(get_db)):
    track = db.get(Track, track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    filename = f"{track.title}.{track.file_format or 'mp3'}"
    return await _range_response(track.file_path, request, filename=filename)
