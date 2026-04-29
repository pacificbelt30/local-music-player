from unittest.mock import MagicMock, patch

from app.models import DownloadJob


def _make_job(**kwargs) -> DownloadJob:
    defaults = {
        "youtube_id": "abc123",
        "status": "pending",
        "progress_pct": 0.0,
    }
    defaults.update(kwargs)
    return DownloadJob(**defaults)


def test_list_queue_empty(client):
    resp = client.get("/api/v1/queue")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_queue(client, db):
    db.add(_make_job())
    db.commit()
    resp = client.get("/api/v1/queue")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_list_queue_filter_status(client, db):
    db.add(_make_job(youtube_id="yt1", status="pending"))
    db.add(_make_job(youtube_id="yt2", status="complete"))
    db.add(_make_job(youtube_id="yt3", status="failed"))
    db.commit()
    resp = client.get("/api/v1/queue?status=pending")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["status"] == "pending"


def test_list_queue_filter_multiple_statuses(client, db):
    db.add(_make_job(youtube_id="yt1", status="pending"))
    db.add(_make_job(youtube_id="yt2", status="complete"))
    db.add(_make_job(youtube_id="yt3", status="failed"))
    db.commit()
    resp = client.get("/api/v1/queue?status=pending,failed")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_cancel_job_not_found(client):
    resp = client.delete("/api/v1/queue/999")
    assert resp.status_code == 404


def test_cancel_job(client, db):
    job = _make_job()
    db.add(job)
    db.commit()
    db.refresh(job)
    resp = client.delete(f"/api/v1/queue/{job.id}")
    assert resp.status_code == 204


def test_cancel_job_with_celery_task(client, db):
    job = _make_job(celery_task_id="celery-task-abc", status="downloading")
    db.add(job)
    db.commit()
    db.refresh(job)
    with patch("app.tasks.celery_app.celery_app.control") as mock_ctrl:
        resp = client.delete(f"/api/v1/queue/{job.id}")
    assert resp.status_code == 204
    mock_ctrl.revoke.assert_called_once_with("celery-task-abc", terminate=True)


def test_retry_job_not_found(client):
    resp = client.post("/api/v1/queue/999/retry")
    assert resp.status_code == 404


def test_retry_job_invalid_status_pending(client, db):
    job = _make_job(status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)
    resp = client.post(f"/api/v1/queue/{job.id}/retry")
    assert resp.status_code == 409


def test_retry_job_invalid_status_downloading(client, db):
    job = _make_job(status="downloading")
    db.add(job)
    db.commit()
    db.refresh(job)
    resp = client.post(f"/api/v1/queue/{job.id}/retry")
    assert resp.status_code == 409


def test_retry_job_failed(client, db):
    job = _make_job(status="failed", error_message="network error")
    db.add(job)
    db.commit()
    db.refresh(job)
    mock_task = MagicMock()
    mock_task.id = "new-celery-id"
    with patch("app.tasks.download.download_track.apply_async", return_value=mock_task):
        resp = client.post(f"/api/v1/queue/{job.id}/retry")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert data["error_message"] is None
    assert data["progress_pct"] == 0.0


def test_retry_job_skipped(client, db):
    job = _make_job(status="skipped")
    db.add(job)
    db.commit()
    db.refresh(job)
    mock_task = MagicMock()
    mock_task.id = "new-celery-id"
    with patch("app.tasks.download.download_track.apply_async", return_value=mock_task):
        resp = client.post(f"/api/v1/queue/{job.id}/retry")
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"
