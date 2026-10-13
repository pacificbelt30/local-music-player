import asyncio
import ipaddress
from urllib.parse import urlsplit

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AppSetting

URL_KEY = "syncthing_url"
API_KEY_KEY = "syncthing_api_key"


def _get_setting(db: Session, key: str) -> str | None:
    row = db.get(AppSetting, key)
    return row.value if row and row.value else None


def _set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))


def get_effective_config(db: Session) -> tuple[str, str]:
    url = _get_setting(db, URL_KEY) or settings.syncthing_url
    api_key = _get_setting(db, API_KEY_KEY) or settings.syncthing_api_key
    return url.rstrip("/"), api_key


def update_config(db: Session, url: str | None, api_key: str | None) -> None:
    if url is not None:
        _set_setting(db, URL_KEY, url.strip().rstrip("/"))
    if api_key is not None:
        _set_setting(db, API_KEY_KEY, api_key.strip())
    db.commit()


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _client(url: str):
    # Local services must not be routed through an Internet proxy. Public
    # custom endpoints retain the normal environment proxy configuration.
    host = urlsplit(url).hostname or ""
    private = "." not in host or host.endswith((".local", ".internal", ".localhost"))
    try:
        private = private or ipaddress.ip_address(host).is_private
    except ValueError:
        pass
    return httpx.AsyncClient(timeout=5.0, trust_env=not private)


def _reason(exc):
    if isinstance(exc, httpx.HTTPStatusError):
        return f"Syncthing HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.RequestError):
        return "Syncthing not reachable"
    return "Invalid response from Syncthing"


async def _get(client, url, path, headers, params=None):
    # Retry only reads, once, to cover connections closing during a restart.
    for attempt in range(2):
        try:
            response = await client.get(f"{url}{path}", headers=headers, params=params or {})
            response.raise_for_status()
            return response.json()
        except httpx.RequestError:
            if attempt:
                raise
        except httpx.HTTPStatusError as exc:
            if attempt or exc.response.status_code not in (502, 503, 504):
                raise
        await asyncio.sleep(0.1)


def _checked(value, expected):
    if isinstance(value, Exception):
        raise value
    if not isinstance(value, expected):
        raise ValueError("Unexpected Syncthing response type")
    return value


async def _folder_summaries(client, url, headers, folders, my_id, connections, connections_known):
    semaphore = asyncio.Semaphore(8)

    async def get(path, params):
        async with semaphore:
            return _checked(await _get(client, url, path, headers, params), dict)

    async def summarize(folder):
        peers = list(dict.fromkeys(d["deviceID"] for d in folder.get("devices", []) if d.get("deviceID") and d["deviceID"] != my_id))
        summary = {k: folder.get(k) for k in ("id", "label", "path", "type")}
        summary.update(paused=folder.get("paused", False), completion_pct=None,
                       need_bytes=0, global_bytes=0, need_items=0, errors=[], peer_ids=peers,
                       connected_devices=sum(bool(connections.get(p, {}).get("connected")) for p in peers),
                       total_devices=len(peers), state="paused" if folder.get("paused") else "unknown")
        if not folder.get("paused"):
            responses = await asyncio.gather(
                get("/rest/db/status", {"folder": folder["id"]}),
                *(get("/rest/db/completion", {"folder": folder["id"], "device": peer}) for peer in peers),
                return_exceptions=True,
            )
            local, remote = responses[0], responses[1:]
            percentages = []
            incomplete = False
            if isinstance(local, Exception):
                summary["errors"].append(_reason(local))
                incomplete = True
            else:
                if not isinstance(local.get("state"), str) or not isinstance(local.get("globalBytes"), (int, float)):
                    incomplete = True
                    summary["errors"].append("Invalid folder status from Syncthing")
                total = local.get("globalBytes", 0)
                summary.update(global_bytes=total, need_bytes=local.get("needBytes", 0),
                               need_items=local.get("needTotalItems", 0), folder_state=local.get("state"))
                percentages.append(max(0, 100 * (total - summary["need_bytes"]) / total) if total else (0 if summary["need_items"] else 100))
                for message in (local.get("error"), local.get("invalid"), local.get("watchError")):
                    if message:
                        summary["errors"].append(str(message))
                if local.get("pullErrors") or local.get("errors"):
                    summary["errors"].append("Folder has synchronization errors")
                if local.get("state") == "error" and not summary["errors"]:
                    summary["errors"].append("Folder is stopped by an error")
            for result in remote:
                if isinstance(result, Exception):
                    summary["errors"].append(_reason(result))
                    incomplete = True
                    continue
                summary["global_bytes"] = max(summary["global_bytes"], result.get("globalBytes", 0))
                summary["need_bytes"] += result.get("needBytes", 0)
                summary["need_items"] += result.get("needItems", 0) + result.get("needDeletes", 0)
                if result.get("remoteState") not in (None, "valid") or result.get("completion") is None:
                    incomplete = True
                else:
                    percentages.append(result["completion"])
            if not incomplete:
                summary["completion_pct"] = min(percentages)
            local_error = not isinstance(local, Exception) and (
                local.get("error") or local.get("invalid") or local.get("watchError")
                or local.get("pullErrors") or local.get("errors") or local.get("state") == "error")
            if local_error:
                summary["state"] = "error"
            elif peers and connections_known and summary["connected_devices"] < len(peers):
                summary["state"] = "disconnected"
            elif incomplete or not connections_known:
                summary["state"] = "unknown"
            elif summary["need_bytes"] or summary["need_items"] or summary.get("folder_state") in ("scanning", "scan-waiting", "syncing", "sync-waiting", "sync-preparing"):
                summary["state"] = "syncing"
            elif not peers:
                summary["state"] = "unshared"
            else:
                summary["state"] = "synced"
        summary["need_bytes_fmt"] = _fmt_bytes(summary["need_bytes"])
        summary["global_bytes_fmt"] = _fmt_bytes(summary["global_bytes"])
        return summary

    return await asyncio.gather(*(summarize(folder) for folder in folders))


async def _snapshot(client, url, headers):
    system = _checked(await _get(client, url, "/rest/system/status", headers), dict)
    if not isinstance(system.get("myID"), str) or not system["myID"]:
        raise ValueError("Syncthing device ID missing")
    folders, connection_data = await asyncio.gather(
        _get(client, url, "/rest/config/folders", headers),
        _get(client, url, "/rest/system/connections", headers), return_exceptions=True,
    )
    errors = []
    connections_known = isinstance(connection_data, dict) and isinstance(connection_data.get("connections"), dict)
    connections = connection_data.get("connections", {}) if connections_known else {}
    if not connections_known:
        errors.append(_reason(connection_data))
    if isinstance(folders, Exception) or not isinstance(folders, list):
        errors.append(_reason(folders))
        summaries = []
    else:
        summaries = await _folder_summaries(client, url, headers, folders, system.get("myID"), connections, connections_known)
    return system, summaries, connections, errors


async def get_syncthing_status(db: Session) -> dict:
    url, api_key = get_effective_config(db)
    if not api_key:
        return {"available": False, "state": "unavailable", "reason": "SYNCTHING_API_KEY not configured"}
    try:
        async with _client(url) as client:
            system, folders, connections, errors = await _snapshot(client, url, {"X-API-Key": api_key})
        states = {f["state"] for f in folders}
        state = next((s for s in ("error", "unknown", "disconnected", "syncing") if s in states), None)
        if state is None:
            state = "unknown" if errors else "unshared" if not folders else "paused" if states == {"paused"} else "unshared" if "unshared" in states else "synced"
        if errors and state != "error":
            state = "unknown"
        active = [f for f in folders if not f["paused"]]
        complete_known = bool(active) and not errors and all(f["completion_pct"] is not None for f in active)
        percentage = sum(f["completion_pct"] * max(f["global_bytes"], 1) for f in active) / sum(max(f["global_bytes"], 1) for f in active) if complete_known else None
        need_bytes = sum(f["need_bytes"] for f in active)
        global_bytes = sum(f["global_bytes"] for f in active)
        peer_ids = set(connections) | {peer for f in folders for peer in f["peer_ids"]}
        peer_ids.discard(system.get("myID"))
        for folder in folders:
            errors.extend(f"{folder.get('label') or folder['id']}: {error}" for error in folder["errors"])
        return {
            "available": True, "state": state, "my_id": system.get("myID"),
            "completion_pct": percentage, "syncing": state == "syncing",
            "need_bytes": need_bytes, "need_bytes_fmt": _fmt_bytes(need_bytes),
            "global_bytes": global_bytes, "global_bytes_fmt": _fmt_bytes(global_bytes),
            "need_items": sum(f["need_items"] for f in active),
            "connected_devices": sum(bool(connections.get(p, {}).get("connected")) for p in peer_ids),
            "total_devices": len(peer_ids), "errors": errors,
        }
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        return {"available": False, "state": "unavailable", "reason": _reason(exc)}


async def test_connection(url: str, api_key: str) -> dict:
    if not api_key:
        return {"ok": False, "reason": "API key is required"}
    try:
        async with _client(url) as client:
            data = _checked(await _get(client, url.rstrip("/"), "/rest/system/status", {"X-API-Key": api_key}), dict)
            if not isinstance(data.get("myID"), str) or not data["myID"]:
                raise ValueError("Syncthing device ID missing")
        return {"ok": True, "my_id": data.get("myID")}
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        return {"ok": False, "reason": _reason(exc)}


async def _proxy_post(db: Session, path: str, params: dict | None = None) -> dict:
    url, api_key = get_effective_config(db)
    if not api_key:
        raise _ConfigError("SYNCTHING_API_KEY not configured")
    async with _client(url) as client:
        resp = await client.post(f"{url}{path}", headers={"X-API-Key": api_key}, params=params or {})
        resp.raise_for_status()
        return {"ok": True}


async def list_folders(db: Session) -> list[dict]:
    url, api_key = get_effective_config(db)
    if not api_key:
        raise _ConfigError("SYNCTHING_API_KEY not configured")
    async with _client(url) as client:
        _, folders, _, errors = await _snapshot(client, url, {"X-API-Key": api_key})
        if errors:
            raise httpx.RequestError("; ".join(errors))
        return folders


async def list_devices(db: Session) -> list[dict]:
    url, api_key = get_effective_config(db)
    if not api_key:
        raise _ConfigError("SYNCTHING_API_KEY not configured")
    async with _client(url) as client:
        system, devices, conns, stats = await asyncio.gather(
            *(_get(client, url, path, {"X-API-Key": api_key}) for path in
              ("/rest/system/status", "/rest/config/devices", "/rest/system/connections", "/rest/stats/device")),
            return_exceptions=True,
        )
        devices = _checked(devices, list)
        system = _checked(system, dict)
        connection_known = isinstance(conns, dict) and isinstance(conns.get("connections"), dict)
        connections = conns.get("connections", {}) if connection_known else {}
        stats = stats if isinstance(stats, dict) else {}
    return [{
        "device_id": d.get("deviceID"), "name": d.get("name"),
        "addresses": d.get("addresses", []), "paused": d.get("paused", False),
        "connected": bool(connections.get(d["deviceID"], {}).get("connected")),
        "connection_known": connection_known,
        "address": connections.get(d["deviceID"], {}).get("address"),
        "last_seen": stats.get(d["deviceID"], {}).get("lastSeen") or connections.get(d["deviceID"], {}).get("lastSeen"),
        "client_version": connections.get(d["deviceID"], {}).get("clientVersion"),
    } for d in devices if d.get("deviceID") and d["deviceID"] != system.get("myID")]


async def rescan_folder(db: Session, folder_id: str) -> dict:
    return await _proxy_post(db, "/rest/db/scan", params={"folder": folder_id})


class _ConfigError(Exception):
    pass
