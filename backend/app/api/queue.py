import asyncio
import json
from typing import AsyncGenerator

import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import DownloadJob
from app.schemas import DownloadJobResponse

router = APIRouter(prefix="/queue", tags=["queue"])
_redis = redis_lib.from_url(settings.redis_url, decode_responses=True)


@router.get("", response_model=list[DownloadJobResponse])
def list_queue(status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(DownloadJob)
    if status:
        statuses = [s.strip() for s in status.split(",")]
        q = q.filter(DownloadJob.status.in_(statuses))
    return q.order_by(DownloadJob.created_at.desc()).limit(200).all()


@router.get("/events")
async def queue_events(db: Session = Depends(get_db)):
    async def event_stream() -> AsyncGenerator[str, None]:
        while True:
            session = next(get_db())
            try:
                active_jobs = session.query(DownloadJob).filter(
                    DownloadJob.status.in_(["pending", "downloading"])
                ).all()

                events = []
                for job in active_jobs:
                    pct = _redis.get(f"job:{job.id}:progress")
                    events.append({
                        "job_id": job.id,
                        "youtube_id": job.youtube_id,
                        "status": job.status,
                        "progress_pct": float(pct) if pct else job.progress_pct,
                    })

                yield f"data: {json.dumps(events)}\n\n"
            finally:
                session.close()

            await asyncio.sleep(1)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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
    job.started_at = None
    job.finished_at = None
    db.flush()

    task = download_track.apply_async(args=[job.id])
    job.celery_task_id = task.id
    db.commit()
    db.refresh(job)
    return job
