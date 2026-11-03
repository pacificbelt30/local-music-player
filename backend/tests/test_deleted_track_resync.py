"""Deleting a library file must not permanently suppress its next sync."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest

from app.models import DownloadJob, Track, UrlSource
from app.tasks.download import resolve_url


def prepare(db, tmp_path, *, status="complete", saved=True):
    source = UrlSource(url="https://www.youtube.com/playlist?list=resync", canonical_url="playlist:resync", url_type="playlist")
    db.add(source)
    db.commit()
    job = DownloadJob(youtube_id="restore", url_source_id=source.id, status=status, progress_pct=100,
                      created_at=datetime.now(timezone.utc)-timedelta(days=3),
                      started_at=datetime.now(timezone.utc)-timedelta(days=3), finished_at=datetime.now(timezone.utc))
    db.add(job)
    if saved:
        path = tmp_path/"restore.mp3"
        path.write_bytes(b"music")
        db.add(Track(youtube_id="restore", title="Restore", file_path=str(path)))
    db.commit()
    return source, job



def test_deleted_file_is_requeued_once_on_next_resolution(client, db, tmp_path):
    source, job = prepare(db, tmp_path)
    source_id, job_id = source.id, job.id
    track = db.query(Track).one()
    response = client.delete(f"/api/v1/tracks/{track.id}?delete_file=true")
    assert response.status_code == 204
    assert not (tmp_path/"restore.mp3").exists()
    with patch("app.tasks.download.SessionLocal", return_value=db), \
         patch("app.tasks.download.ytdlp_service.resolve_url", return_value=[{"id": "restore"}, {"id": "restore"}]), \
         patch("app.tasks.download.download_track.apply_async", return_value=MagicMock(id="restored-attempt")) as dispatch:
        resolve_url.apply(args=[source_id], throw=True)
    assert db.query(DownloadJob).count() == 1
    job = db.get(DownloadJob, job_id)
    dispatch.assert_called_once_with(args=[job_id], countdown=0)
    assert job.status == "pending"
    assert job.celery_task_id == "restored-attempt"
    assert job.progress_pct == 0
    assert job.started_at is None and job.finished_at is None
    assert (datetime.now(timezone.utc)-job.created_at.replace(tzinfo=timezone.utc)).total_seconds() < 10


@pytest.mark.parametrize("status,saved", [("complete", True), ("pending", False), ("downloading", False), ("failed", False)])
def test_existing_files_or_noncomplete_jobs_are_not_duplicated(db, tmp_path, status, saved):
    source, job = prepare(db, tmp_path, status=status, saved=saved)
    job_id = job.id
    with patch("app.tasks.download.SessionLocal", return_value=db), \
         patch("app.tasks.download.ytdlp_service.resolve_url", return_value=[{"id": "restore"}]), \
         patch("app.tasks.download.download_track.apply_async") as dispatch:
        resolve_url.apply(args=[source.id], throw=True)
    dispatch.assert_not_called()
    job = db.get(DownloadJob, job_id)
    assert job.status == status
