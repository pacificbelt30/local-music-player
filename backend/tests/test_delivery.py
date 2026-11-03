"""Readiness requires per-file evidence for the chosen connected device."""

from contextlib import asynccontextmanager
import asyncio
from unittest.mock import patch

import pytest

from app.models import PlaylistSyncTrack, YoutubePlaylistSync
from app.services import delivery


def setup(db, tmp_path, count=1):
    source = YoutubePlaylistSync(
        playlist_id="delivery",
        playlist_name="Delivery",
        dir_name="Delivery",
        target_folder_id="folder",
        target_device_id="phone",
    )
    db.add(source)
    db.flush()
    files = {}
    directory = tmp_path / "Delivery"
    directory.mkdir()
    for i in range(count):
        path = directory / f"{i}.mp3"
        path.write_bytes(b"audio")
        stat = path.stat()
        relative = "Delivery/" + path.name
        db.add(
            PlaylistSyncTrack(
                playlist_sync_id=source.id,
                youtube_id=str(i),
                title=str(i),
                status="complete",
                file_path=str(path),
            )
        )
        version = [{"id": "index", "value": 1}]
        local = {
            "size": stat.st_size,
            "version": version,
            "modifiedS": stat.st_mtime_ns // 1_000_000_000,
            "modifiedNs": stat.st_mtime_ns % 1_000_000_000,
        }
        files[relative] = {
            "global": dict(local),
            "local": dict(local),
            "availability": [{"id": "phone", "fromTemporary": False}],
        }
    db.commit()
    return source, files


@asynccontextmanager
async def client(url):
    yield object()


def run(db, source, files, tmp_path, *, connected=True, folder=True):
    async def get(client, url, path, headers, params=None):
        if path == "/rest/config/folders":
            return (
                [{"id": "folder", "devices": [{"deviceID": "phone"}]}] if folder else []
            )
        if path == "/rest/config/devices":
            return [{"deviceID": "phone"}]
        if path == "/rest/system/connections":
            return {"connections": {"phone": {"connected": connected}}}
        if path == "/rest/db/status":
            return {"state": "idle", "completion": 100}
        if path == "/rest/db/file":
            return files[params["file"]]
        raise AssertionError(path)

    with (
        patch("app.services.delivery.settings.downloads_path", tmp_path),
        patch(
            "app.services.delivery.st.get_effective_config",
            return_value=("http://local", "key"),
        ),
        patch("app.services.delivery.st._client", client),
        patch("app.services.delivery.st._get", side_effect=get),
    ):
        return asyncio.run(delivery.readiness(db, source))


@pytest.fixture(autouse=True)
def clear_cache():
    delivery._cache.clear()
    yield
    delivery._cache.clear()


def test_file_evidence_confirms_selected_device(client, db, tmp_path):
    source, files = setup(db, tmp_path)
    result = run(db, source, files, tmp_path)
    assert result["state"] == "ready" and result["verified"] == 1


@pytest.mark.parametrize(
    "change",
    ["no_peer", "temporary", "wrong_version", "old_mtime", "deleted", "wrong_size"],
)
def test_folder_100_percent_never_overrides_bad_file_evidence(db, tmp_path, change):
    source, files = setup(db, tmp_path)
    data = next(iter(files.values()))
    if change == "no_peer":
        data["availability"] = []
    if change == "temporary":
        data["availability"][0]["fromTemporary"] = True
    if change == "wrong_version":
        data["local"]["version"] = []
    if change == "old_mtime":
        data["local"]["modifiedS"] -= 1
    if change == "deleted":
        data["global"]["deleted"] = True
    if change == "wrong_size":
        data["global"]["size"] += 1
    result = run(db, source, files, tmp_path)
    assert result["state"] == "transferring" and result["verified"] == 0


def test_offline_peer_invalidates_previously_ready_display(db, tmp_path):
    source, files = setup(db, tmp_path)
    assert run(db, source, files, tmp_path)["state"] == "ready"
    assert (
        run(db, source, files, tmp_path, connected=False)["state"] == "device_offline"
    )
    assert run(db, source, files, tmp_path, folder=False)["state"] == "not_shared"


def test_large_playlist_is_verified_in_bounded_batches(db, tmp_path):
    source, files = setup(db, tmp_path, count=51)
    first = run(db, source, files, tmp_path)
    assert first["state"] == "verifying" and first["checked"] == 50
    second = run(db, source, files, tmp_path)
    assert second["state"] == "ready" and second["verified"] == 51


def test_unconfigured_destination_and_missing_local_files_never_show_ready(
    db, tmp_path
):
    source, files = setup(db, tmp_path)
    source.target_device_id = None
    db.commit()
    assert run(db, source, files, tmp_path)["state"] == "server_saved"
    # Simulate external file loss only inside this test's temporary directory.
    next((tmp_path / "Delivery").iterdir()).unlink()
    assert run(db, source, files, tmp_path)["state"] == "needs_attention"


def test_real_syncthing_rfc3339_nanoseconds_are_compared_without_rounding():
    stamp = 1793728333798404843
    info = {"size": 5, "version": ["X:1"], "modified": "2026-11-03T17:52:13.798404843Z"}
    data = {
        "local": dict(info),
        "global": dict(info),
        "availability": [{"id": "peer", "fromTemporary": False}],
    }
    assert delivery.file_confirmed(data, "peer", 5, stamp)
    assert not delivery.file_confirmed(data, "peer", 5, stamp + 1)
    data["local"]["mustRescan"] = True
    assert not delivery.file_confirmed(data, "peer", 5, stamp)
