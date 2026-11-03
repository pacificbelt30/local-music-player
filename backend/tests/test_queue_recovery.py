"""Interrupted downloads recover; healthy workers and conversions stay active."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.api.queue import _mark_stuck_jobs_failed, retry_job
from app.models import DownloadJob


def make_job(db, *, age=timedelta(hours=3), task_id="interrupted", **fields):
    job = DownloadJob(
        youtube_id="recovery", status="downloading", celery_task_id=task_id,
        created_at=datetime.now(timezone.utc) - timedelta(days=2),
        started_at=datetime.now(timezone.utc) - age, **fields,
    )
    db.add(job)
    db.commit()
    return job


@pytest.mark.parametrize("state", ["FAILURE", "REVOKED"])
def test_ended_download_becomes_failed_and_retryable(db, state):
    job = make_job(db, age=timedelta(minutes=20))
    with patch("app.tasks.celery_app.celery_app.AsyncResult") as result:
        result.return_value.state = state
        _mark_stuck_jobs_failed(db)
    db.refresh(job)
    assert job.status == "failed"
    assert job.finished_at is not None
    assert "ended" in job.error_message
    with patch("app.tasks.download.download_track.apply_async", return_value=MagicMock(id="retry-task")):
        retried = retry_job(job.id, db)
    assert retried.status == "pending"
    assert retried.celery_task_id == "retry-task"
    assert retried.started_at is None
    assert retried.finished_at is None
    assert retried.error_message is None


@pytest.mark.parametrize("state", ["PENDING", "STARTED"])
def test_lost_download_recovers_after_worker_restart(db, state):
    job = make_job(db)
    with patch("app.tasks.celery_app.celery_app.AsyncResult") as result, \
         patch("app.api.queue._redis.get", return_value=None), \
         patch("app.tasks.celery_app.celery_app.control.inspect") as inspect:
        result.return_value.state = state
        inspect.return_value.active.return_value = {"restarted-worker": []}
        _mark_stuck_jobs_failed(db)
    db.refresh(job)
    assert job.status == "failed"
    assert "no longer" in job.error_message


def test_recent_download_uses_start_time_not_old_creation_time(db):
    job = make_job(db, age=timedelta(minutes=1))
    with patch("app.tasks.celery_app.celery_app.AsyncResult") as result:
        _mark_stuck_jobs_failed(db)
        result.assert_not_called()
    assert job.status == "downloading"


def test_old_download_with_fresh_progress_is_not_interrupted(db):
    job = make_job(db)
    with patch("app.tasks.celery_app.celery_app.AsyncResult") as result, \
         patch("app.api.queue._redis.get", return_value="0"), \
         patch("app.tasks.celery_app.celery_app.control.inspect") as inspect:
        result.return_value.state = "STARTED"
        _mark_stuck_jobs_failed(db)
        inspect.assert_not_called()
    assert job.status == "downloading"


def test_long_conversion_reported_active_is_not_interrupted(db):
    job = make_job(db)
    with patch("app.tasks.celery_app.celery_app.AsyncResult") as result, \
         patch("app.api.queue._redis.get", return_value=None), \
         patch("app.tasks.celery_app.celery_app.control.inspect") as inspect:
        result.return_value.state = "STARTED"
        inspect.return_value.active.return_value = {"worker": [{"id": job.celery_task_id}]}
        _mark_stuck_jobs_failed(db)
    assert job.status == "downloading"


@pytest.mark.parametrize("response", [None, {}])
def test_missing_worker_reply_is_not_evidence_of_a_crash(db, response):
    job = make_job(db)
    with patch("app.tasks.celery_app.celery_app.AsyncResult") as result, \
         patch("app.api.queue._redis.get", return_value=None), \
         patch("app.tasks.celery_app.celery_app.control.inspect") as inspect:
        result.return_value.state = "PENDING"
        inspect.return_value.active.return_value = response
        _mark_stuck_jobs_failed(db)
    assert job.status == "downloading"


def test_broker_outage_does_not_mark_download_failed(db):
    job = make_job(db)
    with patch("app.tasks.celery_app.celery_app.AsyncResult", side_effect=ConnectionError("offline")):
        _mark_stuck_jobs_failed(db)
    assert job.status == "downloading"
