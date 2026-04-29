from unittest.mock import MagicMock, patch


def test_health_returns_200(client):
    with patch("app.main.redis_lib") as mock_redis_lib, \
         patch("app.main.celery_app", create=True):
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis_lib.from_url.return_value = mock_redis
        resp = client.get("/api/v1/health")
    assert resp.status_code == 200


def test_health_response_schema(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "redis_connected" in data
    assert "db_ok" in data
    assert "worker_active" in data


def test_health_db_ok(client):
    resp = client.get("/api/v1/health")
    data = resp.json()
    # DB should be reachable since we're using in-memory SQLite
    assert data["db_ok"] is True


def test_health_status_degraded_without_redis(client):
    # Without a real Redis, redis_connected should be False → status degraded
    resp = client.get("/api/v1/health")
    data = resp.json()
    assert data["redis_connected"] is False
    assert data["status"] == "degraded"


def test_rescan_library_empty(client):
    resp = client.post("/api/v1/admin/rescan")
    assert resp.status_code == 200
    assert resp.json() == {"removed": 0}


def test_rescan_library_removes_missing_files(client, db):
    from app.models import Track
    track = Track(
        youtube_id="gone1",
        title="Missing File",
        file_path="/nonexistent/path/song.mp3",
    )
    db.add(track)
    db.commit()
    resp = client.post("/api/v1/admin/rescan")
    assert resp.status_code == 200
    assert resp.json()["removed"] == 1


def test_rescan_library_keeps_existing_files(client, db, tmp_path):
    audio_file = tmp_path / "song.mp3"
    audio_file.write_bytes(b"fake audio")
    from app.models import Track
    track = Track(
        youtube_id="real1",
        title="Real File",
        file_path=str(audio_file),
    )
    db.add(track)
    db.commit()
    resp = client.post("/api/v1/admin/rescan")
    assert resp.status_code == 200
    assert resp.json()["removed"] == 0
