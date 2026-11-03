"""Bounded detail pages keep full-list clients compatible and isolate recovery."""

from datetime import datetime, timedelta, timezone
from sqlalchemy import event, text
from app.models import PlaylistSyncTrack, YoutubePlaylistSync


def seed(db, count=123):
    sync = YoutubePlaylistSync(playlist_id="PLpages", playlist_name="Large playlist")
    db.add(sync)
    db.flush()
    db.add_all(
        [
            PlaylistSyncTrack(
                playlist_sync_id=sync.id,
                youtube_id=f"v{i}",
                title=f"Song {i}",
                artist="Artist",
                position=i // 2,
                status="complete",
                file_path=f"/music/{i}.m4a",
            )
            for i in range(count)
        ]
    )
    db.commit()
    return sync.id


def test_pages_are_bounded_and_stable_with_tied_positions(client, db):
    sid = seed(db)
    seen = []
    for offset in (0, 50, 100):
        response = client.get(
            f"/api/v1/youtube/syncs/{sid}/tracks/page?offset={offset}"
        )
        assert response.status_code == 200
        page = response.json()
        assert page["offset"] == offset and page["limit"] == 50 and page["total"] == 123
        assert len(page["items"]) == min(50, 123 - offset)
        assert all(item["stream_url"] for item in page["items"])
        seen.extend(item["id"] for item in page["items"])
    assert len(set(seen)) == 123 and seen == sorted(seen)
    assert len(client.get(f"/api/v1/youtube/syncs/{sid}/tracks").json()) == 123


def test_page_only_materializes_its_50_tracks(client, db):
    sid = seed(db, 1200)
    db.expunge_all()
    loaded = []

    def materialized(session, obj):
        if isinstance(obj, PlaylistSyncTrack):
            loaded.append(obj.id)

    event.listen(db, "loaded_as_persistent", materialized)
    try:
        response = client.get(f"/api/v1/youtube/syncs/{sid}/tracks/page")
    finally:
        event.remove(db, "loaded_as_persistent", materialized)
    assert response.json()["total"] == 1200
    assert len(loaded) == 50
    plan = db.execute(
        text(
            "EXPLAIN QUERY PLAN SELECT * FROM playlist_sync_tracks WHERE playlist_sync_id=:sid AND status!='removed' ORDER BY position,id LIMIT 50"
        ),
        {"sid": sid},
    ).all()
    assert any("ix_sync_tracks_position" in str(row) for row in plan)
    assert not any("TEMP B-TREE" in str(row) for row in plan)


def test_search_and_status_filters_include_artist_and_literal_wildcards(client, db):
    sid = seed(db, 4)
    tracks = db.query(PlaylistSyncTrack).order_by(PlaylistSyncTrack.id).all()
    tracks[0].title = "100%_完成"
    tracks[0].status = "failed"
    tracks[1].title = "100x完成"
    tracks[1].artist = "夜の散歩"
    tracks[1].status = "pending"
    tracks[2].status = "downloading"
    tracks[3].status = "removed"
    db.commit()
    base = f"/api/v1/youtube/syncs/{sid}/tracks/page"
    assert client.get(base).json()["total"] == 3
    page = client.get(base, params={"search": "%_", "status": "failed"}).json()
    assert [item["id"] for item in page["items"]] == [tracks[0].id]
    assert client.get(base, params={"search": "夜の散歩"}).json()["total"] == 1
    assert client.get(base, params={"status": "active"}).json()["total"] == 2
    assert client.get(base, params={"status": "skipped"}).json()["items"] == []


def test_stuck_check_does_not_scan_other_pages(client, db):
    sid = seed(db, 120)
    db.query(PlaylistSyncTrack).update(
        {
            "status": "pending",
            "added_at": datetime.now(timezone.utc) - timedelta(hours=3),
        }
    )
    db.commit()
    response = client.get(f"/api/v1/youtube/syncs/{sid}/tracks/page")
    assert response.status_code == 200
    assert all(item["status"] == "failed" for item in response.json()["items"])
    assert db.query(PlaylistSyncTrack).filter_by(status="failed").count() == 50
    assert db.query(PlaylistSyncTrack).filter_by(status="pending").count() == 70


def test_invalid_page_requests_and_missing_sync(client, db):
    assert client.get("/api/v1/youtube/syncs/999/tracks/page").status_code == 404
    sid = seed(db, 0)
    base = f"/api/v1/youtube/syncs/{sid}/tracks/page"
    assert client.get(base).json() == {
        "items": [],
        "total": 0,
        "offset": 0,
        "limit": 50,
    }
    for query in (
        "limit=0",
        "limit=101",
        "offset=-1",
        "status=removed",
        "search=" + "x" * 201,
    ):
        assert client.get(base + "?" + query).status_code == 422
