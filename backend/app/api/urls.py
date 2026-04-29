from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DownloadJob, Track, UrlSource
from app.schemas import UrlSourceCreate, UrlSourceResponse
from app.tasks.download import resolve_url as resolve_url_task

router = APIRouter(prefix="/urls", tags=["urls"])


@router.post("", response_model=UrlSourceResponse, status_code=201)
def add_url(payload: UrlSourceCreate, db: Session = Depends(get_db)):
    existing = db.query(UrlSource).filter_by(url=payload.url).first()
    if existing:
        raise HTTPException(status_code=409, detail="URL already registered")

    source = UrlSource(
        url=payload.url,
        url_type="video",  # resolved by worker
        audio_format=payload.audio_format,
        audio_quality=payload.audio_quality,
        sync_enabled=payload.sync_enabled,
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    resolve_url_task.apply_async(args=[source.id])
    return source


@router.get("", response_model=list[UrlSourceResponse])
def list_urls(db: Session = Depends(get_db)):
    return db.query(UrlSource).order_by(UrlSource.added_at.desc()).all()


@router.delete("/{url_id}", status_code=204)
def delete_url(url_id: int, delete_files: bool = False, db: Session = Depends(get_db)):
    source = db.get(UrlSource, url_id)
    if not source:
        raise HTTPException(status_code=404, detail="URL not found")

    if delete_files:
        from app.services.file_service import delete_track_files
        for pt in source.playlist_tracks:
            track = pt.track
            if track:
                delete_track_files(track.file_path, track.thumbnail_path)
                db.delete(track)

    db.delete(source)
    db.commit()
