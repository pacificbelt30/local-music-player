from unittest.mock import patch

from app.models import UrlSource
from app.schemas import normalize_youtube_url


def _add_source(db, url: str, url_type: str = "video") -> UrlSource:
    source = UrlSource(url=url, canonical_url=normalize_youtube_url(url), url_type=url_type)
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


# ── Duplicate detection robustness (normalize_youtube_url) ─────────────────

def test_add_url_duplicate_youtu_be_vs_watch(client, db):
    _add_source(db, "https://www.youtube.com/watch?v=norm1")
    with patch("app.api.urls.resolve_url_task.apply_async"):
        resp = client.post("/api/v1/urls", json={"url": "https://youtu.be/norm1"})
    assert resp.status_code == 409


def test_add_url_duplicate_www_vs_bare_host(client, db):
    _add_source(db, "https://www.youtube.com/watch?v=norm2")
    with patch("app.api.urls.resolve_url_task.apply_async"):
        resp = client.post("/api/v1/urls", json={"url": "https://youtube.com/watch?v=norm2"})
    assert resp.status_code == 409


def test_add_url_duplicate_with_tracking_param(client, db):
    _add_source(db, "https://youtu.be/norm3")
    with patch("app.api.urls.resolve_url_task.apply_async"):
        resp = client.post("/api/v1/urls", json={"url": "https://youtu.be/norm3?si=abcDEF123"})
    assert resp.status_code == 409


def test_add_url_duplicate_query_param_order(client, db):
    _add_source(db, "https://www.youtube.com/watch?v=norm4&list=PLxyz")
    with patch("app.api.urls.resolve_url_task.apply_async"):
        resp = client.post(
            "/api/v1/urls", json={"url": "https://www.youtube.com/watch?list=PLxyz&v=norm4"}
        )
    assert resp.status_code == 409


def test_add_url_duplicate_shorts_vs_watch(client, db):
    _add_source(db, "https://www.youtube.com/watch?v=norm5")
    with patch("app.api.urls.resolve_url_task.apply_async"):
        resp = client.post("/api/v1/urls", json={"url": "https://www.youtube.com/shorts/norm5"})
    assert resp.status_code == 409


def test_add_url_duplicate_mobile_subdomain(client, db):
    _add_source(db, "https://www.youtube.com/watch?v=norm6")
    with patch("app.api.urls.resolve_url_task.apply_async"):
        resp = client.post("/api/v1/urls", json={"url": "https://m.youtube.com/watch?v=norm6"})
    assert resp.status_code == 409


def test_add_url_different_videos_not_treated_as_duplicate(client, db):
    _add_source(db, "https://www.youtube.com/watch?v=normA")
    with patch("app.api.urls.resolve_url_task.apply_async"):
        resp = client.post("/api/v1/urls", json={"url": "https://www.youtube.com/watch?v=normB"})
    assert resp.status_code == 201


def test_add_url_duplicate_playlist(client, db):
    _add_source(db, "https://www.youtube.com/playlist?list=PLnorm1", url_type="playlist")
    with patch("app.api.urls.resolve_url_task.apply_async"):
        resp = client.post("/api/v1/urls", json={"url": "https://youtube.com/playlist?list=PLnorm1&extra=1"})
    assert resp.status_code == 409


def test_normalize_youtube_url_video_variants_match():
    variants = [
        "https://www.youtube.com/watch?v=abc123",
        "https://youtube.com/watch?v=abc123",
        "http://youtube.com/watch?v=abc123",
        "https://m.youtube.com/watch?v=abc123",
        "https://youtu.be/abc123",
        "https://youtu.be/abc123?si=shareTrackingId",
        "https://www.youtube.com/shorts/abc123",
        "https://www.youtube.com/embed/abc123",
        "https://www.youtube.com/watch?v=abc123&list=PLsomething&index=3",
    ]
    keys = {normalize_youtube_url(u) for u in variants}
    assert keys == {"video:abc123"}


def test_normalize_youtube_url_distinguishes_different_videos():
    assert normalize_youtube_url("https://youtu.be/abc123") != normalize_youtube_url("https://youtu.be/xyz789")


def test_normalize_youtube_url_video_id_is_case_sensitive():
    # YouTube video IDs are case-sensitive; only the host should be lowercased.
    assert normalize_youtube_url("https://youtu.be/AbC123") != normalize_youtube_url("https://youtu.be/abc123")
