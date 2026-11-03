import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator

import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import case
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.database import get_db
from app.models import DownloadJob
from app.schemas import DownloadJobResponse

router = APIRouter(prefix="/queue", tags=["queue"])
_redis = redis_lib.from_url(settings.redis_url, decode_responses=True)

_STUCK_PENDING_TIMEOUT = timedelta(minutes=10)
_HARD_PENDING_TIMEOUT = timedelta(hours=2)
_TERMINAL_TASK_STATES = {"FAILURE", "REVOKED"}
_ACTIVE_STATUSES = ("pending", "downloading")
_QUEUE_LIMIT = 200
_RECOVERY_INTERVAL = 30
logger = logging.getLogger(__name__)


def _mark_stuck_jobs_failed(db: Session) -> None:
    _mark_stuck_downloads_failed(db)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - _STUCK_PENDING_TIMEOUT
    pending_jobs = db.query(DownloadJob).filter(DownloadJob.status == "pending").all()

    changed = False
    for job in pending_jobs:
        if not job.celery_task_id:
            continue

        created = job.created_at.replace(tzinfo=None) if job.created_at else None
        if created and created > cutoff:
            continue

        from app.tasks.celery_app import celery_app

        state = celery_app.AsyncResult(job.celery_task_id).state
        if state in _TERMINAL_TASK_STATES:
            job.status = "failed"
            job.error_message = "Task left pending after Celery task ended before download started."
            job.finished_at = now
            changed = True
            continue

        hard_cutoff = now - _HARD_PENDING_TIMEOUT
        has_progress = _redis.get(f"job:{job.id}:progress") is not None
        if created and created <= hard_cutoff and not has_progress:
            job.status = "failed"
            job.error_message = "Task stayed pending too long without progress updates."
            job.finished_at = now
            changed = True

    if changed:
        db.commit()


def _mark_stuck_downloads_failed(db: Session) -> None:
    """Recover interrupted downloads without mistaking long conversions for crashes."""
    from app.tasks.celery_app import celery_app

    now = datetime.now(timezone.utc)
    changed = False
    inspected = False
    active_tasks = None
    for job in db.query(DownloadJob).filter(DownloadJob.status == "downloading").all():
        reference = job.started_at or job.created_at
        if reference is None:
            continue
        reference = reference.replace(tzinfo=timezone.utc) if reference.tzinfo is None else reference
        age = now - reference
        if age < _STUCK_PENDING_TIMEOUT:
            continue
        try:
            state = celery_app.AsyncResult(job.celery_task_id).state if job.celery_task_id else None
            if state in _TERMINAL_TASK_STATES:
                reason = "Download worker task ended before completion."
            else:
                if age < _HARD_PENDING_TIMEOUT or _redis.get(f"job:{job.id}:progress") is not None:
                    continue
                if not inspected:
                    active_tasks = celery_app.control.inspect(timeout=1).active()
                    inspected = True
                # No worker reply cannot establish that the task has stopped.
                if not active_tasks or not job.celery_task_id:
                    continue
                if any(task.get("id") == job.celery_task_id for tasks in active_tasks.values() for task in tasks):
                    continue
                reason = "Download worker no longer has this task and progress updates have stopped."
        except Exception:
            # Redis/broker outages are not evidence of a dead worker.
            continue
        job.status = "failed"
        job.error_message = reason
        job.finished_at = now
        changed = True
    if changed:
        db.commit()



@router.get("", response_model=list[DownloadJobResponse])
def list_queue(status: str | None = None, db: Session = Depends(get_db)):
    _mark_stuck_jobs_failed(db)
    q = db.query(DownloadJob)
    if status:
        statuses = [s.strip() for s in status.split(",")]
        q = q.filter(DownloadJob.status.in_(statuses))
    return q.order_by(
        case((DownloadJob.status.in_(_ACTIVE_STATUSES), 0), else_=1),
        DownloadJob.created_at.desc(), DownloadJob.id.desc(),
    ).limit(_QUEUE_LIMIT).all()


def _queue_snapshot(recover: bool = False) -> list[dict]:
    # All blocking database/Redis/Celery work and the session stay in one worker
    # thread. A long-lived stream never holds a database connection between ticks.
    from app.database import SessionLocal

    with SessionLocal() as db:
        if recover:
            try:
                _mark_stuck_jobs_failed(db)
            except Exception:
                db.rollback()
                logger.warning("Queue recovery check unavailable", exc_info=True)
        active_jobs = db.query(DownloadJob).filter(
            DownloadJob.status.in_(_ACTIVE_STATUSES)
        ).order_by(DownloadJob.created_at.desc(), DownloadJob.id.desc()).limit(_QUEUE_LIMIT).all()
        progress = _redis.mget([f"job:{job.id}:progress" for job in active_jobs]) if active_jobs else []
        return [{
            "job_id": job.id,
            "youtube_id": job.youtube_id,
            "status": job.status,
            "progress_pct": float(pct) if pct is not None else job.progress_pct,
        } for job, pct in zip(active_jobs, progress)]


@router.get("/events")
async def queue_events():
    async def event_stream() -> AsyncGenerator[str, None]:
        next_recovery = 0
        loop = asyncio.get_running_loop()
        while True:
            recover = loop.time() >= next_recovery
            events = await run_in_threadpool(_queue_snapshot, recover=recover)
            if recover:
                next_recovery = loop.time() + _RECOVERY_INTERVAL
            yield f"data: {json.dumps(events)}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })


@router.delete("/{job_id}", status_code=204)
def cancel_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.celery_task_id and job.status in ("pending", "downloading"):
        from app.tasks.celery_app import celery_app
        celery_app.control.revoke(job.celery_task_id, terminate=True)

    db.delete(job)
    db.commit()


@router.post("/{job_id}/retry", response_model=DownloadJobResponse)
def retry_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ("failed", "skipped"):
        raise HTTPException(status_code=409, detail="Job is not in a failed/skipped state")

    from app.tasks.download import download_track
    job.status = "pending"
    job.error_message = None
    job.progress_pct = 0.0
    job.created_at = datetime.now(timezone.utc)
    job.started_at = None
    job.finished_at = None
    db.flush()

    task = download_track.apply_async(args=[job.id])
    job.celery_task_id = task.id
    db.commit()
    db.refresh(job)
    return job
