"""Reversible playlist removal: retain files until the explicit retention deadline."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from app.models import AppSetting, PlaylistSyncTrack, SyncEvent, Track
from sqlalchemy import or_
from app.config import settings


def record(db, sync_id, kind, **details):
    db.add(
        SyncEvent(
            sync_id=sync_id, kind=kind, details=json.dumps(details, ensure_ascii=False)
        )
    )


def retention_days(db):
    value = db.get(AppSetting, "removed_track_retention_days")
    return int(value.value) if value else 7


def retained(track):
    return bool(track.file_path and Path(track.file_path).is_file())


def purge_removed(db):
    from app.tasks.sync_playlist import _delete_sync_track_file, _redis

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days(db))
    tracks = (
        db.query(PlaylistSyncTrack)
        .filter(
            PlaylistSyncTrack.status == "removed",
            PlaylistSyncTrack.keep_local == False,
            PlaylistSyncTrack.removed_at < cutoff,
        )
        .all()
    )
    count = 0
    for track in tracks:
        lock = _redis.lock(
            f"lmp:playlist-track:{track.id}", timeout=120, thread_local=False
        )
        if not lock.acquire(blocking=False):
            continue
        try:
            db.refresh(track)
            if track.status != "removed" or track.keep_local:
                continue
            stored_paths = [
                value for value in (track.file_path, track.thumbnail_path) if value
            ]
            shared_sync = (
                db.query(PlaylistSyncTrack)
                .filter(
                    PlaylistSyncTrack.id != track.id,
                    or_(
                        PlaylistSyncTrack.file_path.in_(stored_paths),
                        PlaylistSyncTrack.thumbnail_path.in_(stored_paths),
                    ),
                )
                .first()
            )
            shared_library = (
                db.query(Track)
                .filter(
                    or_(
                        Track.file_path.in_(stored_paths),
                        Track.thumbnail_path.in_(stored_paths),
                    )
                )
                .first()
            )
            if shared_sync is not None or shared_library is not None:
                continue
            roots = (
                settings.downloads_path.resolve(),
                settings.playlists_path.resolve(),
            )
            paths = [
                Path(value).resolve()
                for value in (track.file_path, track.thumbnail_path)
                if value
            ]
            if any(
                not any(path.is_relative_to(root) for root in roots) for path in paths
            ):
                continue
            _delete_sync_track_file(track)
            track.file_path = None
            track.thumbnail_path = None
            count += 1
            db.commit()
        finally:
            lock.release()
    db.commit()
    return count


def failure(db, sync_id, kind, **details):
    """Collapse identical consecutive retry failures into one history entry."""
    last = (
        db.query(SyncEvent)
        .filter_by(sync_id=sync_id)
        .order_by(SyncEvent.id.desc())
        .first()
    )
    if last and last.kind == kind and json.loads(last.details) == details:
        return
    record(db, sync_id, kind, **details)
