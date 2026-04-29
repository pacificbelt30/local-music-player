import pytest
from app.models import Track


def _make_track(**kwargs) -> Track:
    defaults = {
        "youtube_id": "abc123",
        "title": "Test Song",
        "artist": "Test Artist",
        "album": "Test Album",
        "duration_secs": 180,
        "file_path": "/music/test.mp3",
        "file_format": "mp3",
        "file_size_bytes": 1024000,
    }
    defaults.update(kwargs)
    return Track(**defaults)


def test_list_tracks_empty(client):
    resp = client.get("/api/v1/tracks")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_tracks(client, db):
    db.add(_make_track())
    db.commit()
    resp = client.get("/api/v1/tracks")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "Test Song"
    assert data[0]["youtube_id"] == "abc123"


def test_list_tracks_includes_urls(client, db):
    db.add(_make_track())
    db.commit()
    data = client.get("/api/v1/tracks").json()
    assert "stream_url" in data[0]
    assert "download_url" in data[0]


def test_get_track(client, db):
    track = _make_track()
    db.add(track)
    db.commit()
    db.refresh(track)
    resp = client.get(f"/api/v1/tracks/{track.id}")
    assert resp.status_code == 200
    assert resp.json()["youtube_id"] == "abc123"


def test_get_track_not_found(client):
    resp = client.get("/api/v1/tracks/999")
    assert resp.status_code == 404


def test_update_track(client, db):
    track = _make_track()
    db.add(track)
    db.commit()
    db.refresh(track)
    resp = client.patch(f"/api/v1/tracks/{track.id}", json={"title": "Updated Title"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Updated Title"


def test_update_track_partial(client, db):
    track = _make_track()
    db.add(track)
    db.commit()
    db.refresh(track)
    resp = client.patch(f"/api/v1/tracks/{track.id}", json={"artist": "New Artist"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["artist"] == "New Artist"
    assert data["title"] == "Test Song"  # unchanged


def test_update_track_not_found(client):
    resp = client.patch("/api/v1/tracks/999", json={"title": "X"})
    assert resp.status_code == 404


def test_delete_track(client, db):
    track = _make_track()
    db.add(track)
    db.commit()
    db.refresh(track)
    resp = client.delete(f"/api/v1/tracks/{track.id}")
    assert resp.status_code == 204
    assert client.get(f"/api/v1/tracks/{track.id}").status_code == 404


def test_delete_track_not_found(client):
    resp = client.delete("/api/v1/tracks/999")
    assert resp.status_code == 404


def test_list_tracks_search_by_title(client, db):
    db.add(_make_track(youtube_id="yt1", title="Hello World", file_path="/music/1.mp3"))
    db.add(_make_track(youtube_id="yt2", title="Goodbye World", file_path="/music/2.mp3"))
    db.add(_make_track(youtube_id="yt3", title="Something Else", file_path="/music/3.mp3"))
    db.commit()
    resp = client.get("/api/v1/tracks?search=World")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_tracks_search_by_artist(client, db):
    db.add(_make_track(youtube_id="yt1", title="S1", artist="The Beatles", file_path="/music/1.mp3"))
    db.add(_make_track(youtube_id="yt2", title="S2", artist="Rolling Stones", file_path="/music/2.mp3"))
    db.commit()
    resp = client.get("/api/v1/tracks?search=Beatles")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["artist"] == "The Beatles"


def test_list_tracks_filter_artist(client, db):
    db.add(_make_track(youtube_id="yt1", title="S1", artist="Artist A", file_path="/music/1.mp3"))
    db.add(_make_track(youtube_id="yt2", title="S2", artist="Artist B", file_path="/music/2.mp3"))
    db.commit()
    resp = client.get("/api/v1/tracks?artist=Artist+A")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["artist"] == "Artist A"


def test_list_tracks_pagination(client, db):
    for i in range(5):
        db.add(_make_track(youtube_id=f"yt{i}", title=f"Song {i}", file_path=f"/music/{i}.mp3"))
    db.commit()
    resp = client.get("/api/v1/tracks?limit=2&offset=0")
    assert resp.status_code == 200
    assert len(resp.json()) == 2
