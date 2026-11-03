"""File-level destination evidence. Folder completion alone never implies ready."""

import asyncio
from datetime import datetime
import re
from pathlib import Path
import time

from app.config import settings
from app.models import PlaylistSyncTrack
from app.services import syncthing_service as st

_cache = {}


def file_confirmed(data, device, size, mtime_ns):
    local = data.get("local") or {}
    glob = data.get("global") or {}
    if (
        local.get("deleted")
        or glob.get("deleted")
        or local.get("invalid")
        or glob.get("invalid")
    ):
        return False
    if local.get("size") != size or glob.get("size") != size:
        return False
    if not local.get("version") or local.get("version") != glob.get("version"):
        return False
    if "modifiedS" in local and "modifiedNs" in local:
        modified_ns = int(local["modifiedS"]) * 1_000_000_000 + int(local["modifiedNs"])
    else:
        # Syncthing v2 serializes FileInfo times as RFC3339 with nanoseconds.
        match = re.fullmatch(
            r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})",
            local.get("modified", ""),
        )
        if not match:
            return False
        try:
            seconds = int(
                datetime.fromisoformat(
                    match[1] + match[3].replace("Z", "+00:00")
                ).timestamp()
            )
            modified_ns = seconds * 1_000_000_000 + int((match[2] or "").ljust(9, "0"))
        except (ValueError, OverflowError):
            return False
    if modified_ns != mtime_ns or local.get("mustRescan") or local.get("ignored"):
        return False
    return any(
        peer.get("id") == device and peer.get("fromTemporary") is False
        for peer in data.get("availability", [])
    )


async def readiness(db, sync):
    tracks = (
        db.query(PlaylistSyncTrack)
        .filter(
            PlaylistSyncTrack.playlist_sync_id == sync.id,
            PlaylistSyncTrack.status != "removed",
            PlaylistSyncTrack.excluded == False,
        )
        .all()
    )
    result = {
        "sync_id": sync.id,
        "profile_name": sync.profile_name,
        "device_id": sync.target_device_id,
        "total": len(tracks),
        "server_saved": 0,
        "verified": 0,
        "checked": 0,
        "state": "empty",
        "checked_at": None,
    }
    if not tracks:
        return result
    saved = []
    root = (
        settings.downloads_path / (sync.dir_name or "")
        if sync.target_scope == "playlist"
        else settings.downloads_path
    )
    for track in tracks:
        if track.status == "complete" and track.file_path:
            path = Path(track.file_path)
            try:
                stat = path.stat()
                if path.is_file():
                    saved.append((path, stat.st_size, stat.st_mtime_ns))
            except (OSError, ValueError):
                pass
    result["server_saved"] = len(saved)
    if len(saved) < len(tracks):
        result["state"] = (
            "needs_attention"
            if any(
                t.status == "failed"
                or (
                    t.status == "complete"
                    and (not t.file_path or not Path(t.file_path).is_file())
                )
                for t in tracks
            )
            else "downloading"
        )
        return result
    if not sync.target_device_id or not sync.target_folder_id:
        result["state"] = "server_saved"
        return result
    try:
        files = [
            (path.resolve().relative_to(root.resolve()).as_posix(), size, mtime)
            for path, size, mtime in saved
        ]
    except ValueError:
        result["state"] = "unknown"
        return result
    url, key = st.get_effective_config(db)
    if not key:
        result["state"] = "unknown"
        return result
    headers = {"X-API-Key": key}
    try:
        async with st._client(url) as client:
            folders, connection, devices = await asyncio.gather(
                *[
                    st._get(client, url, path, headers)
                    for path in (
                        "/rest/config/folders",
                        "/rest/system/connections",
                        "/rest/config/devices",
                    )
                ]
            )
            folder = next(
                (f for f in folders if f.get("id") == sync.target_folder_id), None
            )
            device = next(
                (d for d in devices if d.get("deviceID") == sync.target_device_id), None
            )
            if (
                not folder
                or folder.get("paused")
                or not device
                or device.get("paused")
                or not any(
                    d.get("deviceID") == sync.target_device_id
                    for d in folder.get("devices", [])
                )
            ):
                result["state"] = "not_shared"
                return result
            result["device_name"] = device.get("name") or sync.target_device_id[:8]
            if (
                not connection.get("connections", {})
                .get(sync.target_device_id, {})
                .get("connected")
            ):
                result["state"] = "device_offline"
                return result
            status = await st._get(
                client,
                url,
                "/rest/db/status",
                headers,
                {"folder": sync.target_folder_id},
            )
            if (
                status.get("state") not in ("idle", "syncing", "scanning")
                or status.get("pullErrors")
                or status.get("error")
            ):
                result["state"] = "unknown"
                return result
            now = time.monotonic()
            semaphore = asyncio.Semaphore(4)
            budget = 50

            async def check(file):
                nonlocal budget
                relative, size, mtime = file
                cache_key = (
                    url,
                    key,
                    sync.target_folder_id,
                    sync.target_device_id,
                    relative,
                    size,
                    mtime,
                )
                cached = _cache.get(cache_key)
                if cached and now - cached[0] < 30:
                    return cached[1]
                if budget <= 0:
                    return None
                budget -= 1
                async with semaphore:
                    try:
                        data = await st._get(
                            client,
                            url,
                            "/rest/db/file",
                            headers,
                            {"folder": sync.target_folder_id, "file": relative},
                        )
                        confirmed = file_confirmed(
                            data, sync.target_device_id, size, mtime
                        )
                        _cache[cache_key] = (now, confirmed)
                        return confirmed
                    except Exception:
                        _cache[cache_key] = (now, None)
                        return None

            evidence = await asyncio.gather(*(check(file) for file in files))
            result["checked"] = sum(value is not None for value in evidence)
            result["verified"] = sum(value is True for value in evidence)
            result["checked_at"] = time.time()
            result["state"] = (
                "ready"
                if result["verified"] == len(files)
                else "verifying"
                if result["checked"] < len(files)
                else "transferring"
            )
            if len(_cache) > 10000:
                for cache_key, value in list(_cache.items()):
                    if now - value[0] >= 30:
                        _cache.pop(cache_key, None)
    except Exception:
        result["state"] = "unknown"
    return result
