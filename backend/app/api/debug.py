from datetime import datetime, timezone, timedelta

import redis as redis_lib
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.config import settings
from app.models import (
    DownloadJob,
    PlaylistSyncTrack,
    Track,
    UrlSource,
    YouTubeOAuthToken,
    YoutubePlaylistSync,
)
from app.schemas import (
    BeatTaskInfo,
    DBStats,
    DebugResponse,
    OAuthDebugInfo,
    QueueStats,
    RedisInfo,
    WorkerInfo,
)

router = APIRouter(prefix="/debug", tags=["admin"])


def _get_worker_info() -> list[WorkerInfo]:
    try:
        from app.tasks.celery_app import celery_app

        insp = celery_app.control.inspect(timeout=2.0)
        active = insp.active() or {}
        stats = insp.stats() or {}

        workers: list[WorkerInfo] = []
        for name, tasks in active.items():
            worker_stats = stats.get(name, {})
            pool = worker_stats.get("pool", {})
            concurrency = pool.get("max-concurrency") or pool.get("processes") or None
            if isinstance(concurrency, list):
                concurrency = len(concurrency)
            task_names = [t.get("name", "unknown") for t in tasks]
            workers.append(
                WorkerInfo(
                    name=name,
                    active_tasks=len(tasks),
                    concurrency=concurrency,
                    active_task_names=task_names,
                )
            )
        # Workers that are registered but idle (in stats but not in active)
        for name in stats:
            if not any(w.name == name for w in workers):
                worker_stats = stats[name]
                pool = worker_stats.get("pool", {})
                concurrency = pool.get("max-concurrency") or pool.get("processes") or None
                if isinstance(concurrency, list):
                    concurrency = len(concurrency)
                workers.append(
                    WorkerInfo(
                        name=name,
                        active_tasks=0,
                        concurrency=concurrency,
                        active_task_names=[],
                    )
                )
        return workers
    except Exception:
        return []


def _get_queue_stats(db: Session) -> QueueStats:
    rows = (
        db.query(DownloadJob.status, func.count(DownloadJob.id))
        .group_by(DownloadJob.status)
        .all()
    )
    counts = {status: cnt for status, cnt in rows}
    stuck_threshold = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=10)
    stuck = (
        db.query(func.count(DownloadJob.id))
        .filter(DownloadJob.status == "pending", DownloadJob.created_at < stuck_threshold)
        .scalar()
        or 0
    )
    total = sum(counts.values())
    return QueueStats(
        pending=counts.get("pending", 0),
        downloading=counts.get("downloading", 0),
        complete=counts.get("complete", 0),
        failed=counts.get("failed", 0),
        skipped=counts.get("skipped", 0),
        total=total,
        stuck=stuck,
    )


def _get_oauth_info(db: Session) -> OAuthDebugInfo:
    token = db.query(YouTubeOAuthToken).first()
    if not token:
        return OAuthDebugInfo(authenticated=False)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    expiry = token.token_expiry
    expires_in: int | None = None
    is_expired = False
    needs_refresh = False

    if expiry:
        delta = expiry - now
        expires_in = int(delta.total_seconds())
        is_expired = expires_in <= 0
        needs_refresh = expires_in < 300  # < 5 mins

    return OAuthDebugInfo(
        authenticated=True,
        token_expiry=expiry,
        expires_in_seconds=expires_in,
        scope=token.scope,
        is_expired=is_expired,
        needs_refresh=needs_refresh,
    )


def _get_redis_info() -> RedisInfo:
    try:
        r = redis_lib.from_url(settings.redis_url)
        info = r.info()
        return RedisInfo(
            connected=True,
            used_memory_human=info.get("used_memory_human"),
            connected_clients=info.get("connected_clients"),
            uptime_in_seconds=info.get("uptime_in_seconds"),
            total_commands_processed=info.get("total_commands_processed"),
        )
    except Exception:
        return RedisInfo(connected=False)


def _get_db_stats(db: Session) -> DBStats:
    return DBStats(
        tracks=db.query(func.count(Track.id)).scalar() or 0,
        download_jobs=db.query(func.count(DownloadJob.id)).scalar() or 0,
        url_sources=db.query(func.count(UrlSource.id)).scalar() or 0,
        youtube_syncs=db.query(func.count(YoutubePlaylistSync.id)).scalar() or 0,
        playlist_sync_tracks=db.query(func.count(PlaylistSyncTrack.id)).scalar() or 0,
    )


def _get_beat_schedule() -> list[BeatTaskInfo]:
    try:
        from app.tasks.celery_app import celery_app

        schedule = celery_app.conf.beat_schedule or {}
        result = []
        for entry_name, entry in schedule.items():
            sched = entry.get("schedule")
            sched_str = str(sched) if sched is not None else "unknown"
            result.append(BeatTaskInfo(name=entry.get("task", entry_name), schedule=sched_str))
        return result
    except Exception:
        return []


@router.get("", response_model=DebugResponse)
def get_debug(db: Session = Depends(get_db)):
    workers = _get_worker_info()
    return DebugResponse(
        server_time=datetime.now(timezone.utc),
        workers=workers,
        worker_count=len(workers),
        queue=_get_queue_stats(db),
        oauth=_get_oauth_info(db),
        redis=_get_redis_info(),
        db=_get_db_stats(db),
        beat_schedule=_get_beat_schedule(),
    )
