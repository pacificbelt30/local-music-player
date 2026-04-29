from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Track
from app.schemas import TrackResponse, TrackUpdate

router = APIRouter(prefix="/tracks", tags=["tracks"])


def _track_to_response(track: Track, request: Request) -> TrackResponse:
    base = str(request.base_url).rstrip("/")
    data = TrackResponse.model_validate(track)
    data.thumbnail_url = f"{base}/api/v1/thumbnails/{track.id}" if track.thumbnail_path else None
    data.stream_url = f"{base}/api/v1/stream/{track.id}"
    data.download_url = f"{base}/api/v1/files/{track.id}/download"
    return data


@router.get("", response_model=list[TrackResponse])
def list_tracks(
    request: Request,
    search: str | None = None,
    artist: str | None = None,
    sort: str = "added_at",
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    q = db.query(Track)
    if search:
        q = q.filter(or_(Track.title.ilike(f"%{search}%"), Track.artist.ilike(f"%{search}%")))
    if artist:
        q = q.filter(Track.artist.ilike(f"%{artist}%"))

    sort_col = getattr(Track, sort, Track.added_at)
    q = q.order_by(sort_col.desc())

    tracks = q.limit(limit).offset(offset).all()
    return [_track_to_response(t, request) for t in tracks]


@router.get("/{track_id}", response_model=TrackResponse)
def get_track(track_id: int, request: Request, db: Session = Depends(get_db)):
    track = db.get(Track, track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")
    return _track_to_response(track, request)


@router.patch("/{track_id}", response_model=TrackResponse)
def update_track(track_id: int, payload: TrackUpdate, request: Request, db: Session = Depends(get_db)):
    track = db.get(Track, track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(track, field, value)
    db.commit()
    db.refresh(track)
    return _track_to_response(track, request)


@router.delete("/{track_id}", status_code=204)
def delete_track(track_id: int, delete_file: bool = False, db: Session = Depends(get_db)):
    track = db.get(Track, track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    if delete_file:
        from app.services.file_service import delete_track_files
        delete_track_files(track.file_path, track.thumbnail_path)

    db.delete(track)
    db.commit()
