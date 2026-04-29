from unittest.mock import patch

from app.models import UrlSource


def _add_source(db, url: str, url_type: str = "video") -> UrlSource:
    source = UrlSource(url=url, url_type=url_type)
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def test_list_urls_empty(client):
    resp = client.get("/api/v1/urls")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_urls(client, db):
    _add_source(db, "https://www.youtube.com/watch?v=abc123")
    resp = client.get("/api/v1/urls")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_add_url(client):
    with patch("app.api.urls.resolve_url_task.apply_async"):
        resp = client.post("/api/v1/urls", json={
            "url": "https://www.youtube.com/watch?v=abc123",
            "audio_format": "mp3",
            "audio_quality": "192",
        })
    assert resp.status_code == 201
    data = resp.json()
    assert data["url"] == "https://www.youtube.com/watch?v=abc123"
    assert data["audio_format"] == "mp3"
    assert data["audio_quality"] == "192"
    assert data["sync_enabled"] is True


def test_add_url_youtu_be(client):
    with patch("app.api.urls.resolve_url_task.apply_async"):
        resp = client.post("/api/v1/urls", json={"url": "https://youtu.be/abc123"})
    assert resp.status_code == 201


def test_add_url_non_youtube_rejected(client):
    resp = client.post("/api/v1/urls", json={"url": "https://example.com/video"})
    assert resp.status_code == 422


def test_add_url_duplicate(client, db):
    url = "https://www.youtube.com/watch?v=dup1"
    _add_source(db, url)
    with patch("app.api.urls.resolve_url_task.apply_async"):
        resp = client.post("/api/v1/urls", json={"url": url})
    assert resp.status_code == 409


def test_add_url_triggers_celery_task(client):
    with patch("app.api.urls.resolve_url_task.apply_async") as mock_task:
        client.post("/api/v1/urls", json={"url": "https://www.youtube.com/watch?v=xyz"})
    mock_task.assert_called_once()


def test_delete_url_not_found(client):
    resp = client.delete("/api/v1/urls/999")
    assert resp.status_code == 404


def test_delete_url(client, db):
    source = _add_source(db, "https://www.youtube.com/watch?v=del1")
    resp = client.delete(f"/api/v1/urls/{source.id}")
    assert resp.status_code == 204


def test_delete_url_removes_from_list(client, db):
    source = _add_source(db, "https://www.youtube.com/watch?v=del2")
    client.delete(f"/api/v1/urls/{source.id}")
    assert client.get("/api/v1/urls").json() == []


def test_add_url_with_flac_format(client):
    with patch("app.api.urls.resolve_url_task.apply_async"):
        resp = client.post("/api/v1/urls", json={
            "url": "https://www.youtube.com/watch?v=flac1",
            "audio_format": "flac",
            "audio_quality": "best",
        })
    assert resp.status_code == 201
    data = resp.json()
    assert data["audio_format"] == "flac"
    assert data["audio_quality"] == "best"
