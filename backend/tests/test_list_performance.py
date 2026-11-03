"""List queries stay bounded and pagination has a deterministic tie-breaker."""

from datetime import datetime

from sqlalchemy import event

from app.api.youtube_playlists import list_syncs
from app.models import PlaylistSyncTrack, Track, YoutubePlaylistSync


def test_sync_list_counts_without_loading_tracks_or_querying_per_playlist(db):
    for i in range(40):
        sync = YoutubePlaylistSync(playlist_id=f"PL{i}", playlist_name=f"List {i}")
        db.add(sync)
        db.flush()
        if i == 0:
            continue
        for j, status in enumerate(
            ("complete", "failed", "pending", "skipped", "removed")
        ):
            db.add(
                PlaylistSyncTrack(
                    playlist_sync_id=sync.id,
                    youtube_id=f"v{j}",
                    title="Track",
                    status=status,
                )
            )
    db.commit()
    db.expunge_all()
    selects, loaded = [], []

    def sql(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    def materialized(session, obj):
        if isinstance(obj, PlaylistSyncTrack):
            loaded.append(obj)

    event.listen(db.bind, "before_cursor_execute", sql)
    event.listen(db, "loaded_as_persistent", materialized)
    try:
        result = list_syncs(db)
    finally:
        event.remove(db.bind, "before_cursor_execute", sql)
        event.remove(db, "loaded_as_persistent", materialized)
    assert len(result) == 40
    assert len(selects) == 2
    assert not loaded
    counts = {r.playlist_id: (r.track_count, r.downloaded_count) for r in result}
    assert counts["PL0"] == (0, 0)
    assert all(counts[f"PL{i}"] == (4, 1) for i in range(1, 40))


def test_track_pages_with_identical_dates_do_not_skip_or_repeat(client, db):
    for i in range(7):
        db.add(
            Track(
                youtube_id=f"v{i}",
                title="Same title",
                file_path=f"/files/{i}.m4a",
                file_format="m4a",
                added_at=datetime(2026, 1, 1),
            )
        )
    db.commit()
    ids = []
    for offset in range(0, 7, 2):
        response = client.get(f"/api/v1/tracks?limit=2&offset={offset}")
        assert response.status_code == 200
        ids.extend(row["id"] for row in response.json())
    assert ids == sorted({t.id for t in db.query(Track).all()}, reverse=True)
    assert client.get("/api/v1/tracks?sort=__table__").status_code == 200


def test_track_page_size_cannot_accidentally_load_entire_library(client):
    for query in ("limit=-1", "limit=201", "limit=0", "offset=-1"):
        assert client.get(f"/api/v1/tracks?{query}").status_code == 422
