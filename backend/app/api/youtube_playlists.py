"""YouTube playlist sync API: OAuth2 flow + sync management."""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import case, func, or_, and_
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import PlaylistSyncTrack, YoutubePlaylistSync, YouTubeOAuthToken
from app.schemas import (
    PlaylistPrivacyUpdate,
    YouTubeAuthStatus,
    YouTubePlaylistInfo,
    YouTubeTokenInput,
    YoutubePlaylistSyncCreate,
    YoutubePlaylistSyncResponse,
    YoutubePlaylistSyncUpdate,
    PlaylistSyncTrackResponse,
    PlaylistSyncTrackPage,
)
from app.services import sync_dirs, youtube_api_service, ytdlp_service
from app.api.stream import _range_response

router = APIRouter(prefix="/youtube", tags=["youtube"])


_STUCK_TRACK_TIMEOUT = timedelta(hours=2)


def _mark_stuck_playlist_tracks_failed(db: Session, sync_id: int, track_ids=None) -> bool:
    now = datetime.now(timezone.utc)
    cutoff = now - _STUCK_TRACK_TIMEOUT

    q = db.query(PlaylistSyncTrack).filter(
        PlaylistSyncTrack.playlist_sync_id == sync_id,
        or_(
            and_(PlaylistSyncTrack.status == "pending", PlaylistSyncTrack.added_at <= now - timedelta(minutes=10)),
            and_(PlaylistSyncTrack.status == "downloading", PlaylistSyncTrack.started_at <= now - timedelta(minutes=10)),
        ),
    )
    if track_ids is not None:
        if not track_ids:
            return False
        q = q.filter(PlaylistSyncTrack.id.in_(track_ids))
    tracks = q.all()

    from app.tasks.celery_app import celery_app
    from app.tasks.sync_playlist import _redis

    changed = False
    inspected = False
    active_tasks = None
    for track in tracks:
        # Discovery time says nothing about how long a download has run.
        reference = track.started_at if track.status == "downloading" else track.added_at
        if reference is None:
            continue  # Legacy downloads have no reliable start time.
        reference = reference if reference.tzinfo else reference.replace(tzinfo=timezone.utc)
        if now - reference < timedelta(minutes=10):
            continue
        reason = None
        if not track.celery_task_id:
            if track.status == "pending" and reference <= cutoff:
                reason = "Track stayed pending too long without starting download."
        else:
            try:
                state = celery_app.AsyncResult(track.celery_task_id).state
                if state in {"FAILURE", "REVOKED"}:
                    reason = "Playlist download task ended before completion."
                elif track.status == "downloading" and reference <= cutoff:
                    if _redis.get(f"pstrack:{track.id}:progress") is not None:
                        continue
                    if not inspected:
                        active_tasks = celery_app.control.inspect(timeout=1).active()
                        inspected = True
                    if not active_tasks:
                        continue
                    if any(task.get("id") == track.celery_task_id for tasks in active_tasks.values() for task in tasks):
                        continue
                    reason = "Download appeared to stall or worker crashed."
                # A pending task may still be waiting in a long broker queue.
            except Exception:
                continue  # An unavailable broker cannot prove a task has stopped.
        if reason:
            track.status = "failed"
            track.error_message = reason
            changed = True

    if changed:
        db.commit()
    return changed



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
    youtube_api_service.record_authorization(record, payload.model_dump(), now, issued_here=False)
    db.commit()
    from app.services.recovery import resume_after_authorization
    resume_after_authorization(db)
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
    youtube_api_service.record_authorization(record, data, now)
    db.commit()
    from app.services.recovery import resume_after_authorization
    resume_after_authorization(db)
    return RedirectResponse(url="/?youtube_auth=success")


@router.get("/auth/status", response_model=YouTubeAuthStatus)
def auth_status(db: Session = Depends(get_db)):
    record = db.query(YouTubeOAuthToken).first()
    return youtube_api_service.token_status(record)


@router.post("/auth/check", response_model=YouTubeAuthStatus)
def check_auth(db: Session = Depends(get_db)):
    """Explicitly verify the refresh token; normal status reads do not use Google."""
    if not settings.youtube_client_id or not settings.youtube_client_secret:
        return youtube_api_service.token_status(db.query(YouTubeOAuthToken).first())
    try:
        youtube_api_service.get_fresh_access_token(db, force=True)
    except (httpx.HTTPStatusError, httpx.RequestError):
        pass  # Safe failure details are persisted by the refresh helper.
    return youtube_api_service.token_status(db.query(YouTubeOAuthToken).first())


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


@router.patch("/playlists/{playlist_id}/privacy")
def change_playlist_privacy(
    playlist_id: str, payload: PlaylistPrivacyUpdate, db: Session = Depends(get_db)
):
    """Change a playlist's privacy status (e.g. private -> unlisted) via the API.

    Lets the user flip a private playlist to unlisted so it can be synced by
    its share URL afterwards (no per-sync API calls). Requires a write-scoped
    token; a read-only token yields 403.
    """
    access_token = youtube_api_service.get_fresh_access_token(db)
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated with YouTube")
    try:
        youtube_api_service.update_playlist_privacy(
            playlist_id, access_token, payload.privacy_status
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (401, 403):
            raise HTTPException(
                status_code=403,
                detail=(
                    "プレイリストの公開設定を変更する権限がありません。"
                    " 書き込みスコープ (youtube) で再認証してください。"
                ),
            )
        raise HTTPException(status_code=502, detail=f"YouTube API error: {e}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"YouTube API error: {e}")
    return {"playlist_id": playlist_id, "privacy_status": payload.privacy_status}


# ── Sync configs ──────────────────────────────────────────────────────────────

def _sync_track_counts(db: Session, sync_ids: list[int]) -> dict[int, tuple[int, int]]:
    if not sync_ids:
        return {}
    rows = db.query(
        PlaylistSyncTrack.playlist_sync_id,
        func.count(PlaylistSyncTrack.id),
        func.sum(case((PlaylistSyncTrack.status == "complete", 1), else_=0)),
    ).filter(
        PlaylistSyncTrack.playlist_sync_id.in_(sync_ids),
        PlaylistSyncTrack.status != "removed",
    ).group_by(PlaylistSyncTrack.playlist_sync_id).all()
    return {sync_id: (total, complete) for sync_id, total, complete in rows}


def _build_sync_response(sync: YoutubePlaylistSync, db: Session, counts=None) -> YoutubePlaylistSyncResponse:
    if counts is None:
        counts = _sync_track_counts(db, [sync.id]).get(sync.id, (0, 0))
    track_count, downloaded_count = counts
    r = YoutubePlaylistSyncResponse.model_validate(sync)
    r.track_count = track_count
    r.downloaded_count = downloaded_count
    return r


@router.get("/syncs", response_model=list[YoutubePlaylistSyncResponse])
def list_syncs(db: Session = Depends(get_db)):
    syncs = db.query(YoutubePlaylistSync).order_by(YoutubePlaylistSync.created_at.desc()).all()
    counts = _sync_track_counts(db, [sync.id for sync in syncs])
    return [_build_sync_response(s, db, counts.get(s.id, (0, 0))) for s in syncs]


@router.post("/syncs", response_model=YoutubePlaylistSyncResponse, status_code=201)
def create_sync(payload: YoutubePlaylistSyncCreate, db: Session = Depends(get_db)):
    from app.services.download_preferences import apply_download_defaults
    apply_download_defaults(payload, db)
    if payload.source_type == "url":
        if not payload.source_url:
            raise HTTPException(status_code=422, detail="source_url is required for URL-based sync")
        try:
            info = ytdlp_service.get_playlist_info(payload.source_url)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to resolve playlist: {e}")
        playlist_id = info["playlist_id"]
        playlist_name = info["playlist_title"] or playlist_id
    else:
        if not payload.playlist_id:
            raise HTTPException(status_code=422, detail="playlist_id is required for API-based sync")
        playlist_id = payload.playlist_id
        playlist_name = payload.playlist_name

    existing = db.query(YoutubePlaylistSync).filter_by(
        playlist_id=playlist_id, audio_format=payload.audio_format
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Playlist already configured for sync with this format")

    from app.services.profiles import snapshot
    sync = YoutubePlaylistSync(
        **snapshot(db, payload.profile_id),
        playlist_id=playlist_id,
        playlist_name=playlist_name,
        # Fixed at creation so the folder never changes once downloads start
        dir_name=sync_dirs.allocate_sync_dir_name(db, playlist_name, payload.audio_format),
        source_type=payload.source_type,
        source_url=payload.source_url,
        audio_format=payload.audio_format,
        audio_quality=payload.audio_quality,
        enabled=payload.enabled,
    )
    db.add(sync)
    db.flush()

    # The name is now shared, so every sync of this name carries its format:
    # move an existing plain-named sync (folder and tracked files included)
    base = sync_dirs.playlist_sync_dir_name(playlist_name)
    others = db.query(YoutubePlaylistSync).filter(YoutubePlaylistSync.id != sync.id).all()
    for other in others:
        other_dir = other.dir_name or sync_dirs.playlist_sync_dir_name(other.playlist_name)
        if other_dir == base:
            sync_dirs.relabel_sync_dir(
                db, other,
                sync_dirs.allocate_sync_dir_name(db, other.playlist_name, other.audio_format, exclude_id=other.id),
            )

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
    if payload.audio_format is not None and payload.audio_format != sync.audio_format:
        conflict = db.query(YoutubePlaylistSync).filter(
            YoutubePlaylistSync.id != sync.id,
            YoutubePlaylistSync.playlist_id == sync.playlist_id,
            YoutubePlaylistSync.audio_format == payload.audio_format,
        ).first()
        if conflict:
            raise HTTPException(status_code=409, detail="Another sync for this playlist already uses this format")
        # Re-label the directory (folder and tracked files included) only when
        # it carried the old format suffix; an unsuffixed folder stays put.
        if sync.dir_name == sync_dirs.playlist_sync_dir_name(sync.playlist_name, sync.audio_format):
            sync_dirs.relabel_sync_dir(
                db, sync,
                sync_dirs.allocate_sync_dir_name(db, sync.playlist_name, payload.audio_format, exclude_id=sync.id),
            )
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

    # Persist the choice with the deletion, including across Redis restarts.
    from app.models import AppSetting
    for track in sync.tracks:
        if track.celery_task_id and track.status in ("pending", "downloading", "failed"):
            db.merge(AppSetting(key=f"deleted-download:{track.celery_task_id}", value="files" if delete_files else "keep"))

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
    if sync.source_type == "api":
        access_token = youtube_api_service.get_fresh_access_token(db)
        if not access_token:
            raise HTTPException(status_code=401, detail="Not authenticated with YouTube")

    from app.tasks.sync_playlist import sync_youtube_playlist
    sync_youtube_playlist.apply_async(args=[sync.id], kwargs={"manual": True})
    return {"queued": True}


# ── Tracks in a sync ──────────────────────────────────────────────────────────

def _sync_tracks_to_response(tracks):
    result = []
    for t in tracks:
        r = PlaylistSyncTrackResponse.model_validate(t)
        if t.thumbnail_path:
            r.thumbnail_url = f"/api/v1/youtube/syncs/tracks/{t.id}/thumbnail"
        if t.status == "complete" and t.file_path:
            r.stream_url = f"/api/v1/youtube/syncs/tracks/{t.id}/stream"
        result.append(r)
    return result


@router.get("/syncs/{sync_id}/tracks/page", response_model=PlaylistSyncTrackPage)
def list_sync_track_page(
    sync_id: int,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: str = Query("", max_length=200),
    status: Literal["active", "complete", "failed", "skipped"] | None = None,
    db: Session = Depends(get_db),
):
    if db.get(YoutubePlaylistSync, sync_id) is None:
        raise HTTPException(404, "Sync not found")
    q = db.query(PlaylistSyncTrack).filter(
        PlaylistSyncTrack.playlist_sync_id == sync_id,
        PlaylistSyncTrack.status != "removed",
    )
    if search.strip():
        q = q.filter(or_(
            PlaylistSyncTrack.title.icontains(search.strip(), autoescape=True),
            PlaylistSyncTrack.artist.icontains(search.strip(), autoescape=True),
        ))
    if status:
        q = q.filter(PlaylistSyncTrack.status.in_(["pending", "downloading"]) if status == "active" else PlaylistSyncTrack.status == status)
    ordered = q.order_by(PlaylistSyncTrack.position, PlaylistSyncTrack.id)
    tracks = ordered.limit(limit).offset(offset).all()
    # Only inspect downloads on the displayed page; polling never materializes
    # all pending downloads in a large playlist.
    if _mark_stuck_playlist_tracks_failed(db, sync_id, [track.id for track in tracks]):
        tracks = ordered.limit(limit).offset(offset).all()
    return PlaylistSyncTrackPage(items=_sync_tracks_to_response(tracks), total=q.count(), offset=offset, limit=limit)


@router.get("/syncs/{sync_id}/tracks", response_model=list[PlaylistSyncTrackResponse])
def list_sync_tracks(sync_id: int, db: Session = Depends(get_db)):
    sync = db.get(YoutubePlaylistSync, sync_id)
    if not sync:
        raise HTTPException(status_code=404, detail="Sync not found")

    _mark_stuck_playlist_tracks_failed(db, sync_id)

    tracks = (
        db.query(PlaylistSyncTrack)
        .filter(PlaylistSyncTrack.playlist_sync_id == sync_id, PlaylistSyncTrack.status != "removed")
        .order_by(PlaylistSyncTrack.position, PlaylistSyncTrack.id)
        .all()
    )

    return _sync_tracks_to_response(tracks)


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
