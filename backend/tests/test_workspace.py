"""Product workflows: previews are reviewable, retries idempotent, changes reversible."""

from datetime import datetime, timedelta, timezone
import json
from unittest.mock import MagicMock, patch

import pytest

from app.models import (
    AppSetting,
    DownloadJob,
    MediaProfile,
    PlaylistSyncTrack,
    SyncEvent,
    UrlSource,
    YoutubePlaylistSync,
)


def sync(db, pid="PLtest", **fields):
    row = YoutubePlaylistSync(
        playlist_id=pid,
        playlist_name=pid,
        source_type="url",
        source_url="https://www.youtube.com/playlist?list=" + pid,
        **fields,
    )
    db.add(row)
    db.commit()
    return row


def track(db, sync, **fields):
    data = dict(
        playlist_sync_id=sync.id, youtube_id="vid", title="Track", status="complete"
    )
    data.update(fields)
    row = PlaylistSyncTrack(**data)
    db.add(row)
    db.commit()
    return row


def test_builtin_profiles_and_copy_edit_do_not_change_existing_sync(client, db):
    presets = client.get("/api/v1/workspace/profiles").json()
    assert {p["id"] for p in presets} == {-1, -2, -3}
    old = sync(db, profile_id=-1, profile_name="スマホ用")
    response = client.post(
        "/api/v1/workspace/profiles",
        json={"name": "My phone", "audio_format": "m4a", "audio_quality": "320"},
    )
    assert response.status_code == 201
    saved = response.json()
    saved.pop("id")
    saved.pop("builtin")
    saved["audio_quality"] = "192"
    pid = response.json()["id"]
    assert (
        client.put(f"/api/v1/workspace/profiles/{pid}", json=saved).status_code == 200
    )
    db.refresh(old)
    assert old.audio_format == "mp3"
    assert client.delete(f"/api/v1/workspace/profiles/{pid}").status_code == 204
    assert db.get(YoutubePlaylistSync, old.id).profile_name == "スマホ用"


@pytest.mark.parametrize(
    "payload",
    [
        {"name": " "},
        {"name": "Bad", "audio_format": "exe"},
        {"name": "Bad", "target_folder_id": "folder"},
    ],
)
def test_invalid_profiles_rejected(client, payload):
    assert client.post("/api/v1/workspace/profiles", json=payload).status_code == 422


def test_profile_defaults_snapshot_applies_to_new_sources(client, db):
    with patch("app.api.urls.resolve_url_task.apply_async"):
        response = client.post(
            "/api/v1/urls", json={"url": "https://youtu.be/profile", "profile_id": -3}
        )
    assert response.status_code == 201
    assert response.json()["audio_format"] == "mp4"
    assert response.json()["profile_name"] == "動画保存"


def test_intake_preview_detects_mixed_duplicate_unavailable_and_registered_urls(
    client, db
):
    old = sync(db, pid="PLold")

    def info(url):
        return {"playlist_id": "PLold", "playlist_title": "Old", "entries": []}

    with (
        patch("app.services.ytdlp_service.get_playlist_info", side_effect=info),
        patch(
            "app.services.ytdlp_service.resolve_url",
            return_value=[{"id": "new", "title": "Video", "url_type": "video"}],
        ),
    ):
        response = client.post(
            "/api/v1/workspace/intake/preview",
            json={
                "text": "https://youtu.be/new\nhttps://www.youtube.com/watch?v=new&si=x\nhttps://youtube.com/playlist?list=PLold\nhttps://evil.example/x"
            },
        )
    assert response.status_code == 200
    assert [item["state"] for item in response.json()["items"]] == [
        "available",
        "duplicate",
        "registered",
        "unavailable",
    ]
    assert db.query(UrlSource).count() == 0
    assert db.query(YoutubePlaylistSync).count() == 1


def preview(client, urls="https://youtu.be/new", profile_id=-1):
    with patch(
        "app.services.ytdlp_service.resolve_url",
        return_value=[{"id": "new", "title": "New", "url_type": "video"}],
    ):
        return client.post(
            "/api/v1/workspace/intake/preview",
            json={"text": urls, "profile_id": profile_id},
        ).json()


def test_intake_commit_is_idempotent_and_queues_once(client, db):
    plan = preview(client)
    body = {"token": plan["token"], "indices": [0]}
    with patch("app.tasks.download.resolve_url.apply_async") as send:
        first = client.post("/api/v1/workspace/intake/commit", json=body)
        second = client.post("/api/v1/workspace/intake/commit", json=body)
    assert first.status_code == 200 and second.status_code == 200
    assert db.query(UrlSource).count() == 1
    assert db.query(UrlSource).one().audio_format == "m4a"
    assert send.call_count == 1


def test_intake_recovers_dispatch_failure_without_duplicate_registration(client, db):
    plan = preview(client)
    body = {"token": plan["token"], "indices": [0]}
    with patch(
        "app.tasks.download.resolve_url.apply_async",
        side_effect=ConnectionError("offline"),
    ):
        first = client.post("/api/v1/workspace/intake/commit", json=body).json()
    assert (
        first["results"]["0"]["state"] == "created" and first["results"]["0"]["error"]
    )
    with patch("app.tasks.download.resolve_url.apply_async") as send:
        second = client.post("/api/v1/workspace/intake/commit", json=body).json()
    assert (
        second["complete"] and send.call_count == 1 and db.query(UrlSource).count() == 1
    )


def test_expired_or_wrong_intake_selection_is_rejected(client, db):
    plan = preview(client)
    row = db.get(AppSetting, "plan:" + plan["token"])
    data = json.loads(row.value)
    data["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    row.value = json.dumps(data)
    db.commit()
    assert (
        client.post(
            "/api/v1/workspace/intake/commit",
            json={"token": plan["token"], "indices": [0]},
        ).status_code
        == 409
    )
    fresh = preview(client)
    assert (
        client.post(
            "/api/v1/workspace/intake/commit",
            json={"token": fresh["token"], "indices": [-1]},
        ).status_code
        == 422
    )


def test_account_search_can_select_private_playlist_without_changing_privacy(
    client, db
):
    with (
        patch(
            "app.services.youtube_api_service.get_fresh_access_token",
            return_value="token",
        ),
        patch(
            "app.services.youtube_api_service.get_my_playlists",
            return_value=[
                {"playlist_id": "Private", "title": "Study mix", "item_count": 1}
            ],
        ),
        patch("app.services.youtube_api_service.update_playlist_privacy") as privacy,
    ):
        plan = client.post(
            "/api/v1/workspace/intake/preview", json={"text": "study", "profile_id": -2}
        ).json()
        with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async"):
            result = client.post(
                "/api/v1/workspace/intake/commit",
                json={"token": plan["token"], "indices": [0]},
            )
    assert result.status_code == 200
    assert db.query(YoutubePlaylistSync).one().source_type == "api"
    privacy.assert_not_called()


def test_profile_apply_requires_fresh_preview_and_is_idempotent(client, db, tmp_path):
    source = sync(db)
    file = tmp_path / "file.mp3"
    file.write_bytes(b"original")
    item = track(db, source, file_path=str(file), file_size_bytes=8)
    plan = client.post(
        "/api/v1/workspace/profiles/-2/preview", json={"sync_ids": [source.id]}
    ).json()
    assert plan["redownload_count"] == 1 and plan["existing_bytes"] == 8
    with patch(
        "app.tasks.sync_playlist.download_playlist_sync_track.apply_async"
    ) as send:
        response = client.post(
            "/api/v1/workspace/profiles/apply", json={"token": plan["token"]}
        )
        assert response.status_code == 200
        repeat = client.post(
            "/api/v1/workspace/profiles/apply", json={"token": plan["token"]}
        )
    assert send.call_count == 1
    db.refresh(source)
    assert source.audio_format == "flac"
    assert (
        file.read_bytes() == b"original"
    )  # Old file survives until its replacement succeeds.
    assert repeat.json()["applied"] == 1


def test_profile_apply_rejects_changed_state_and_active_downloads(client, db):
    source = sync(db)
    item = track(db, source)
    plan = client.post(
        "/api/v1/workspace/profiles/-3/preview", json={"sync_ids": [source.id]}
    ).json()
    item.status = "downloading"
    db.commit()
    assert (
        client.post(
            "/api/v1/workspace/profiles/apply", json={"token": plan["token"]}
        ).status_code
        == 409
    )
    fresh = client.post(
        "/api/v1/workspace/profiles/-3/preview", json={"sync_ids": [source.id]}
    ).json()
    assert (
        client.post(
            "/api/v1/workspace/profiles/apply", json={"token": fresh["token"]}
        ).status_code
        == 409
    )


def test_profile_apply_checks_all_targets_before_any_changes(client, db):
    one = sync(db, "PLsame", audio_format="mp3")
    two = sync(db, "PLsame", audio_format="m4a")
    plan = client.post(
        "/api/v1/workspace/profiles/-2/preview", json={"sync_ids": [one.id, two.id]}
    ).json()
    assert (
        client.post(
            "/api/v1/workspace/profiles/apply", json={"token": plan["token"]}
        ).status_code
        == 409
    )
    db.refresh(one)
    db.refresh(two)
    assert (one.audio_format, two.audio_format) == ("mp3", "m4a")


def test_history_retains_removed_files_and_restoration_prevents_repeat_removal(
    client, db, tmp_path
):
    from app.tasks.sync_playlist import sync_youtube_playlist

    source = sync(db)
    file = tmp_path / "old.mp3"
    file.write_bytes(b"music")
    item = track(db, source, file_path=str(file))
    with (
        patch("app.tasks.sync_playlist.SessionLocal", return_value=db),
        patch.object(db, "close"),
        patch(
            "app.services.ytdlp_service.get_playlist_info", return_value={"entries": []}
        ),
    ):
        sync_youtube_playlist.run(source.id)
        db.refresh(item)
        assert item.status == "removed" and file.exists()
        history = client.get(f"/api/v1/workspace/syncs/{source.id}/history").json()
        assert history["events"][0]["details"]["removed"][0]["id"] == item.id
        response = client.post(
            f"/api/v1/workspace/syncs/{source.id}/tracks/{item.id}/restore"
        )
        assert response.json()["redownload"] is False
        sync_youtube_playlist.run(source.id)
    db.refresh(item)
    assert item.status == "complete" and item.keep_local and file.exists()


def test_retention_purge_only_deletes_expired_unprotected_removals(
    client, db, tmp_path, monkeypatch
):
    monkeypatch.setattr("app.config.settings.downloads_path", tmp_path)
    from app.services.sync_history import purge_removed

    source = sync(db)
    file = tmp_path / "old.mp3"
    file.write_bytes(b"music")
    item = track(
        db,
        source,
        status="removed",
        removed_at=datetime.now(timezone.utc) - timedelta(days=8),
        file_path=str(file),
    )
    assert purge_removed(db) == 1
    assert not file.exists() and item.file_path is None
    with patch(
        "app.tasks.sync_playlist.download_playlist_sync_track.apply_async"
    ) as send:
        response = client.post(
            f"/api/v1/workspace/syncs/{source.id}/tracks/{item.id}/restore"
        )
    assert response.json()["redownload"] and send.call_count == 1


def test_error_groups_skip_and_restore_both_playlist_tracks_and_manual_jobs(client, db):
    source = sync(db)
    item = track(db, source, status="failed", error_message="Video unavailable")
    job = DownloadJob(
        youtube_id="manual", status="failed", error_message="Private video"
    )
    db.add(job)
    db.commit()
    group = client.get("/api/v1/workspace/issues").json()[0]
    assert group["category"] == "unavailable" and group["count"] == 2
    assert (
        client.post("/api/v1/workspace/issues/unavailable/skip").json()["skipped"] == 2
    )
    db.refresh(item)
    assert item.excluded
    groups = client.get("/api/v1/workspace/issues").json()
    assert groups[0]["category"] == "excluded"
    with patch(
        "app.tasks.download.download_track.apply_async",
        return_value=MagicMock(id="restored"),
    ):
        assert (
            client.post(f"/api/v1/workspace/jobs/{job.id}/restore").status_code == 200
        )
    db.refresh(job)
    assert job.status == "pending"


def test_successful_reauthorization_retries_grouped_auth_failures(client, db):
    source = sync(db)
    source.source_type = "api"
    source.last_error = "invalid_grant"
    db.commit()
    with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async") as send:
        response = client.post(
            "/api/v1/youtube/auth/token",
            json={"access_token": "renewed", "expires_in": 3600},
        )
    assert response.status_code == 200
    send.assert_called_once_with(args=[source.id], kwargs={"manual": False})


def test_reauthorization_does_not_restart_paused_syncs(client, db):
    source = sync(db)
    source.source_type = "api"
    source.last_error = "invalid_grant"
    source.enabled = False
    db.commit()
    with patch("app.tasks.sync_playlist.sync_youtube_playlist.apply_async") as send:
        client.post("/api/v1/youtube/auth/token", json={"access_token": "renewed"})
    send.assert_not_called()


def test_failed_batch_does_not_resurrect_a_source_deleted_before_retry(client, db):
    plan = preview(client)
    body = {"token": plan["token"], "indices": [0]}
    with patch(
        "app.tasks.download.resolve_url.apply_async",
        side_effect=ConnectionError("offline"),
    ):
        client.post("/api/v1/workspace/intake/commit", json=body)
    source = db.query(UrlSource).one()
    db.delete(source)
    db.commit()
    with patch("app.tasks.download.resolve_url.apply_async") as send:
        response = client.post("/api/v1/workspace/intake/commit", json=body).json()
    assert response["results"]["0"]["state"] == "cancelled"
    assert db.query(UrlSource).count() == 0
    send.assert_not_called()


def test_released_retained_track_is_rechecked_by_next_sync(client, db, tmp_path):
    from app.tasks.sync_playlist import sync_youtube_playlist

    source = sync(db)
    path = tmp_path / "held.mp3"
    path.write_bytes(b"music")
    item = track(db, source, file_path=str(path), keep_local=True)
    assert client.post(
        f"/api/v1/workspace/syncs/{source.id}/tracks/{item.id}/release"
    ).json()["released"]
    with (
        patch("app.tasks.sync_playlist.SessionLocal", return_value=db),
        patch.object(db, "close"),
        patch(
            "app.services.ytdlp_service.get_playlist_info", return_value={"entries": []}
        ),
    ):
        sync_youtube_playlist.run(source.id)
    db.refresh(item)
    assert item.status == "removed" and path.exists()


def test_history_bounds_large_details_and_paginates_retained_tracks(client, db):
    source = sync(db)
    for i in range(201):
        db.add(
            PlaylistSyncTrack(
                playlist_sync_id=source.id,
                youtube_id=str(i),
                title=str(i),
                status="removed",
            )
        )
    db.add(
        SyncEvent(
            sync_id=source.id,
            kind="sync",
            details=json.dumps(
                {
                    "added": [{"id": i, "title": str(i)} for i in range(250)],
                    "removed": [],
                }
            ),
        )
    )
    db.commit()
    first = client.get(f"/api/v1/workspace/syncs/{source.id}/history").json()
    assert len(first["retained"]) == 200 and first["has_more"]
    assert first["events"][0]["details"]["added_count"] == 250
    assert len(first["events"][0]["details"]["added"]) == 100
    second = client.get(
        f"/api/v1/workspace/syncs/{source.id}/history?retained_offset=200"
    ).json()
    assert len(second["retained"]) == 1 and second["retained_total"] == 201


def test_expired_records_outside_app_storage_are_not_automatically_deleted(
    client, db, tmp_path
):
    from app.services.sync_history import purge_removed

    source = sync(db)
    path = tmp_path / "outside.mp3"
    path.write_bytes(b"owned elsewhere")
    item = track(
        db,
        source,
        status="removed",
        removed_at=datetime.now(timezone.utc) - timedelta(days=8),
        file_path=str(path),
    )
    assert purge_removed(db) == 0 and path.exists()


def test_retention_days_are_validated(client):
    assert (
        client.patch(
            "/api/v1/settings", json={"removed_track_retention_days": 0}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            "/api/v1/settings", json={"removed_track_retention_days": 91}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            "/api/v1/settings", json={"removed_track_retention_days": 14}
        ).json()["removed_track_retention_days"]
        == 14
    )


def test_search_marks_registered_items_before_commit(client, db):
    source = sync(db, "Private")
    with (
        patch(
            "app.services.youtube_api_service.get_fresh_access_token",
            return_value="token",
        ),
        patch(
            "app.services.youtube_api_service.get_my_playlists",
            return_value=[
                {
                    "playlist_id": "Private",
                    "title": "Study mix",
                    "privacy_status": "private",
                }
            ],
        ),
    ):
        result = client.post(
            "/api/v1/workspace/intake/preview", json={"text": "study"}
        ).json()
    assert result["items"][0]["state"] == "registered"


def test_profile_snapshot_destination_change_needs_no_redownload(client, db):
    source = sync(db)
    track(db, source)
    new = client.post(
        "/api/v1/workspace/profiles",
        json={
            "name": "Destination",
            "audio_format": "mp3",
            "audio_quality": "192",
            "target_folder_id": "folder",
            "target_device_id": "phone",
        },
    ).json()
    preview_ = client.post(
        f"/api/v1/workspace/profiles/{new['id']}/preview",
        json={"sync_ids": [source.id]},
    ).json()
    assert preview_["redownload_count"] == 0
    with patch(
        "app.tasks.sync_playlist.download_playlist_sync_track.apply_async"
    ) as send:
        response = client.post(
            "/api/v1/workspace/profiles/apply", json={"token": preview_["token"]}
        )
    assert response.status_code == 200
    db.refresh(source)
    assert source.target_device_id == "phone"
    send.assert_not_called()


def test_download_failures_do_not_mistake_yt_dlp_login_for_data_api_oauth(db):
    from app.services.recovery import classify

    assert classify("oauth2 token invalid_client", api=True) == "configuration"
    assert classify("oauth2 token invalid_grant", api=True) == "auth"
    source = sync(db)
    source.source_type = "api"
    db.commit()
    track(db, source, status="failed", error_message="HTTP 401 unauthorized")
    from app.services.recovery import groups

    assert groups(db)[0]["category"] != "auth"


def test_repeated_identical_failures_are_collapsed_but_recovery_separates_them(db):
    from app.services.sync_history import failure, record

    source = sync(db)
    failure(db, source.id, "fetch_failed", error="timeout")
    db.commit()
    failure(db, source.id, "fetch_failed", error="timeout")
    db.commit()
    assert db.query(SyncEvent).count() == 1
    record(db, source.id, "download_recovered", tracks=[])
    db.commit()
    failure(db, source.id, "fetch_failed", error="timeout")
    db.commit()
    assert db.query(SyncEvent).count() == 3


def test_reload_can_resume_previously_committed_batch_even_after_preview_expiry(
    client, db
):
    plan = preview(client)
    body = {"token": plan["token"], "indices": [0]}
    with patch(
        "app.tasks.download.resolve_url.apply_async",
        side_effect=ConnectionError("offline"),
    ):
        client.post("/api/v1/workspace/intake/commit", json=body)
    row = db.get(AppSetting, "plan:" + plan["token"])
    data = json.loads(row.value)
    data["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    row.value = json.dumps(data)
    db.commit()
    issues = client.get("/api/v1/workspace/issues").json()
    assert any(group["category"] == "intake" for group in issues)
    with patch("app.tasks.download.resolve_url.apply_async") as send:
        response = client.post("/api/v1/workspace/issues/intake/retry")
    assert response.json()["queued"] == 1 and send.call_count == 1
    assert db.query(UrlSource).count() == 1
    assert not any(
        group["category"] == "intake"
        for group in client.get("/api/v1/workspace/issues").json()
    )


def test_automatic_retention_keeps_files_referenced_by_other_library_records(
    db, tmp_path, monkeypatch
):
    from app.models import Track
    from app.services.sync_history import purge_removed

    monkeypatch.setattr("app.config.settings.downloads_path", tmp_path)
    source = sync(db)
    path = tmp_path / "shared.mp3"
    path.write_bytes(b"shared")
    track(
        db,
        source,
        status="removed",
        removed_at=datetime.now(timezone.utc) - timedelta(days=8),
        file_path=str(path),
    )
    db.add(
        Track(youtube_id="shared", title="Other library reference", file_path=str(path))
    )
    db.commit()
    assert purge_removed(db) == 0 and path.exists()


def test_sidecar_deletion_with_dots_in_title_only_removes_exact_fixture(tmp_path):
    from app.services.file_service import delete_track_files

    media = tmp_path / "Song.v2.mp3"
    correct = tmp_path / "Song.v2.info.json"
    unrelated = tmp_path / "Song.info.json"
    media.write_bytes(b"music")
    correct.write_text("{}")
    unrelated.write_text("unrelated")
    delete_track_files(str(media))
    assert not media.exists() and not correct.exists() and unrelated.exists()
