"""YouTube playlist sync API: OAuth2 flow + sync management."""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import PlaylistSyncTrack, YoutubePlaylistSync, YouTubeOAuthToken
from app.schemas import (
    YouTubeAuthStatus,
    YouTubePlaylistInfo,
    YouTubeTokenInput,
    YoutubePlaylistSyncCreate,
    YoutubePlaylistSyncResponse,
    YoutubePlaylistSyncUpdate,
    PlaylistSyncTrackResponse,
)
from app.services import youtube_api_service
from app.api.stream import _range_response

router = APIRouter(prefix="/youtube", tags=["youtube"])


_STUCK_TRACK_TIMEOUT = timedelta(hours=2)


def _mark_stuck_playlist_tracks_failed(db: Session, sync_id: int) -> None:
    now = datetime.now(timezone.utc)
    cutoff = now - _STUCK_TRACK_TIMEOUT

    tracks = db.query(PlaylistSyncTrack).filter(
        PlaylistSyncTrack.playlist_sync_id == sync_id,
        PlaylistSyncTrack.status.in_(["pending", "downloading"]),
    ).all()

    changed = False
    for track in tracks:
        ref_time = track.added_at
        if not ref_time:
            continue
        ref = ref_time if ref_time.tzinfo else ref_time.replace(tzinfo=timezone.utc)
        if ref > cutoff:
            continue

        if track.status == "pending":
            track.status = "failed"
            track.error_message = "Track stayed pending too long without starting download."
        else:
            track.status = "failed"
            track.error_message = "Download appeared to stall or worker crashed."
        changed = True

    if changed:
        db.commit()



# ── OAuth2 ────────────────────────────────────────────────────────────────────

@router.get("/auth/url")
def get_auth_url():
    if not settings.youtube_client_id:
        raise HTTPException(status_code=400, detail="YOUTUBE_CLIENT_ID not configured")
    return {"url": youtube_api_service.get_auth_url()}


@router.post("/auth/token", status_code=200)
def set_token_directly(payload: YouTubeTokenInput, db: Session = Depends(get_db)):
    """Store an OAuth access token (and optional refresh token) pasted directly by the user."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    expiry = now + timedelta(seconds=payload.expires_in)

    record = db.query(YouTubeOAuthToken).first()
    if record:
        record.access_token = payload.access_token
        if payload.refresh_token:
            record.refresh_token = payload.refresh_token
        record.token_expiry = expiry
        record.scope = None
    else:
        record = YouTubeOAuthToken(
            access_token=payload.access_token,
            refresh_token=payload.refresh_token,
            token_expiry=expiry,
            scope=None,
        )
        db.add(record)
    db.commit()
    return {"ok": True}


@router.get("/auth/callback")
def oauth_callback(code: str = Query(...), db: Session = Depends(get_db)):
    if not settings.youtube_client_id:
        raise HTTPException(status_code=400, detail="YOUTUBE_CLIENT_ID not configured")
    try:
        data = youtube_api_service.exchange_code(code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {e}")

    now = datetime.now(timezone.utc)
    from datetime import timedelta
    expiry = now + timedelta(seconds=data.get("expires_in", 3600))

    record = db.query(YouTubeOAuthToken).first()
    if record:
        record.access_token = data["access_token"]
        if "refresh_token" in data:
            record.refresh_token = data["refresh_token"]
        record.token_expiry = expiry
        record.scope = data.get("scope")
    else:
        record = YouTubeOAuthToken(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", ""),
            token_expiry=expiry,
            scope=data.get("scope"),
        )
        db.add(record)
    db.commit()
    return RedirectResponse(url="/?youtube_auth=success")


@router.get("/auth/status", response_model=YouTubeAuthStatus)
def auth_status(db: Session = Depends(get_db)):
    record = db.query(YouTubeOAuthToken).first()
    if not record:
        return YouTubeAuthStatus(authenticated=False)
    return YouTubeAuthStatus(authenticated=True, scope=record.scope)


@router.delete("/auth", status_code=204)
def revoke_auth(db: Session = Depends(get_db)):
    record = db.query(YouTubeOAuthToken).first()
    if record:
        try:
            youtube_api_service.revoke_token(record.access_token)
        except Exception:
            pass
        db.delete(record)
        db.commit()


# ── Playlists from account ────────────────────────────────────────────────────

@router.get("/playlists", response_model=list[YouTubePlaylistInfo])
def list_account_playlists(db: Session = Depends(get_db)):
    access_token = youtube_api_service.get_fresh_access_token(db)
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated with YouTube")
    try:
        items = youtube_api_service.get_my_playlists(access_token)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"YouTube API error: {e}")
    return [YouTubePlaylistInfo(**item) for item in items]


# ── Sync configs ──────────────────────────────────────────────────────────────

def _build_sync_response(sync: YoutubePlaylistSync, db: Session) -> YoutubePlaylistSyncResponse:
    tracks = db.query(PlaylistSyncTrack).filter_by(playlist_sync_id=sync.id).all()
    track_count = len([t for t in tracks if t.status != "removed"])
    downloaded_count = len([t for t in tracks if t.status == "complete"])
    r = YoutubePlaylistSyncResponse.model_validate(sync)
    r.track_count = track_count
    r.downloaded_count = downloaded_count
    return r


@router.get("/syncs", response_model=list[YoutubePlaylistSyncResponse])
def list_syncs(db: Session = Depends(get_db)):
    syncs = db.query(YoutubePlaylistSync).order_by(YoutubePlaylistSync.created_at.desc()).all()
    return [_build_sync_response(s, db) for s in syncs]


@router.post("/syncs", response_model=YoutubePlaylistSyncResponse, status_code=201)
def create_sync(payload: YoutubePlaylistSyncCreate, db: Session = Depends(get_db)):
    existing = db.query(YoutubePlaylistSync).filter_by(playlist_id=payload.playlist_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="Playlist already configured for sync")

    sync = YoutubePlaylistSync(
        playlist_id=payload.playlist_id,
        playlist_name=payload.playlist_name,
        audio_format=payload.audio_format,
        audio_quality=payload.audio_quality,
        enabled=payload.enabled,
    )
    db.add(sync)
    db.commit()
    db.refresh(sync)

    if sync.enabled:
        from app.tasks.sync_playlist import sync_youtube_playlist
        sync_youtube_playlist.apply_async(args=[sync.id])

    return _build_sync_response(sync, db)


@router.patch("/syncs/{sync_id}", response_model=YoutubePlaylistSyncResponse)
def update_sync(sync_id: int, payload: YoutubePlaylistSyncUpdate, db: Session = Depends(get_db)):
    sync = db.get(YoutubePlaylistSync, sync_id)
    if not sync:
        raise HTTPException(status_code=404, detail="Sync not found")
    if payload.audio_format is not None:
        sync.audio_format = payload.audio_format
    if payload.audio_quality is not None:
        sync.audio_quality = payload.audio_quality
    if payload.enabled is not None:
        sync.enabled = payload.enabled
    db.commit()
    return _build_sync_response(sync, db)


@router.delete("/syncs/{sync_id}", status_code=204)
def delete_sync(sync_id: int, delete_files: bool = False, db: Session = Depends(get_db)):
    sync = db.get(YoutubePlaylistSync, sync_id)
    if not sync:
        raise HTTPException(status_code=404, detail="Sync not found")

    if delete_files:
        from app.tasks.sync_playlist import _delete_sync_track_file
        for track in sync.tracks:
            _delete_sync_track_file(track)
        # Try to remove the playlist directory if empty
        playlist_dir = settings.playlists_path / sync.playlist_id
        try:
            if playlist_dir.exists():
                import shutil
                shutil.rmtree(playlist_dir)
        except Exception:
            pass

    db.delete(sync)
    db.commit()


@router.post("/syncs/{sync_id}/run", status_code=202)
def run_sync_now(sync_id: int, db: Session = Depends(get_db)):
    sync = db.get(YoutubePlaylistSync, sync_id)
    if not sync:
        raise HTTPException(status_code=404, detail="Sync not found")
    access_token = youtube_api_service.get_fresh_access_token(db)
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated with YouTube")

    from app.tasks.sync_playlist import sync_youtube_playlist
    sync_youtube_playlist.apply_async(args=[sync.id])
    return {"queued": True}


# ── Tracks in a sync ──────────────────────────────────────────────────────────

@router.get("/syncs/{sync_id}/tracks", response_model=list[PlaylistSyncTrackResponse])
def list_sync_tracks(sync_id: int, db: Session = Depends(get_db)):
    sync = db.get(YoutubePlaylistSync, sync_id)
    if not sync:
        raise HTTPException(status_code=404, detail="Sync not found")

    _mark_stuck_playlist_tracks_failed(db, sync_id)

    tracks = (
        db.query(PlaylistSyncTrack)
        .filter(PlaylistSyncTrack.playlist_sync_id == sync_id, PlaylistSyncTrack.status != "removed")
        .order_by(PlaylistSyncTrack.position)
        .all()
    )

    result = []
    for t in tracks:
        r = PlaylistSyncTrackResponse.model_validate(t)
        if t.thumbnail_path:
            r.thumbnail_url = f"/api/v1/youtube/syncs/tracks/{t.id}/thumbnail"
        if t.status == "complete" and t.file_path:
            r.stream_url = f"/api/v1/youtube/syncs/tracks/{t.id}/stream"
        result.append(r)
    return result


# ── Stream / thumbnail for playlist sync tracks ───────────────────────────────

@router.get("/syncs/tracks/{track_id}/stream")
async def stream_sync_track(track_id: int, request: Request, db: Session = Depends(get_db)):
    track = db.get(PlaylistSyncTrack, track_id)
    if not track or not track.file_path:
        raise HTTPException(status_code=404, detail="Track not found")
    return await _range_response(track.file_path, request)


@router.get("/syncs/tracks/{track_id}/thumbnail")
def get_sync_track_thumbnail(track_id: int, db: Session = Depends(get_db)):
    track = db.get(PlaylistSyncTrack, track_id)
    if not track or not track.thumbnail_path:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    if not os.path.exists(track.thumbnail_path):
        raise HTTPException(status_code=404, detail="Thumbnail file not found on disk")
    ext = Path(track.thumbnail_path).suffix.lower()
    content_type = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(ext, "image/jpeg")
    return FileResponse(track.thumbnail_path, media_type=content_type, headers={"Cache-Control": "public, max-age=86400"})
