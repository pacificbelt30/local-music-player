import asyncio

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
    """Return (url, api_key), DB overrides falling back to env settings."""
    url = _get_setting(db, URL_KEY) or settings.syncthing_url
    api_key = _get_setting(db, API_KEY_KEY) or settings.syncthing_api_key
    return url, api_key


def update_config(db: Session, url: str | None, api_key: str | None) -> None:
    if url is not None:
        _set_setting(db, URL_KEY, url.strip())
    if api_key is not None:
        _set_setting(db, API_KEY_KEY, api_key.strip())
    db.commit()


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


async def get_syncthing_status(db: Session) -> dict:
    """Fetch Syncthing status from its REST API."""
    url, api_key = get_effective_config(db)
    if not api_key:
        return {"available": False, "reason": "SYNCTHING_API_KEY not configured"}

    headers = {"X-API-Key": api_key}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            system_resp, completion_resp, conns_resp = await asyncio.gather(
                client.get(f"{url}/rest/system/status", headers=headers),
                client.get(f"{url}/rest/db/completion", headers=headers),
                client.get(f"{url}/rest/system/connections", headers=headers),
            )
            system_resp.raise_for_status()
            system = system_resp.json()
            completion = completion_resp.json() if completion_resp.status_code == 200 else {}
            conns_data = conns_resp.json() if conns_resp.status_code == 200 else {}

        connections = conns_data.get("connections", {})
        connected_devices = sum(1 for c in connections.values() if c.get("connected"))
        total_devices = len(connections)
        need_bytes = completion.get("needBytes", 0)
        global_bytes = completion.get("globalBytes", 0)
        need_items = completion.get("needItems", 0)

        return {
            "available": True,
            "my_id": system.get("myID"),
            "completion_pct": completion.get("completion", 100),
            "syncing": need_bytes > 0,
            "need_bytes": need_bytes,
            "need_bytes_fmt": _fmt_bytes(need_bytes),
            "global_bytes": global_bytes,
            "global_bytes_fmt": _fmt_bytes(global_bytes),
            "need_items": need_items,
            "connected_devices": connected_devices,
            "total_devices": total_devices,
        }
    except (httpx.ConnectError, httpx.TimeoutException):
        return {"available": False, "reason": "Syncthing not reachable"}
    except httpx.HTTPStatusError as e:
        return {"available": False, "reason": f"HTTP {e.response.status_code}"}


async def test_connection(url: str, api_key: str) -> dict:
    """Probe a Syncthing instance with the given URL and API key without saving."""
    if not api_key:
        return {"ok": False, "reason": "API key is required"}
    headers = {"X-API-Key": api_key}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{url}/rest/system/status", headers=headers)
            resp.raise_for_status()
            data = resp.json()
        return {"ok": True, "my_id": data.get("myID")}
    except (httpx.ConnectError, httpx.TimeoutException):
        return {"ok": False, "reason": "Syncthing not reachable"}
    except httpx.HTTPStatusError as e:
        return {"ok": False, "reason": f"HTTP {e.response.status_code}"}


async def _proxy_get(db: Session, path: str) -> dict | list:
    url, api_key = get_effective_config(db)
    if not api_key:
        raise _ConfigError("SYNCTHING_API_KEY not configured")
    headers = {"X-API-Key": api_key}
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{url}{path}", headers=headers)
        resp.raise_for_status()
        return resp.json()


async def _proxy_post(db: Session, path: str, params: dict | None = None) -> dict:
    url, api_key = get_effective_config(db)
    if not api_key:
        raise _ConfigError("SYNCTHING_API_KEY not configured")
    headers = {"X-API-Key": api_key}
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(f"{url}{path}", headers=headers, params=params or {})
        resp.raise_for_status()
        return {"ok": True}


async def list_folders(db: Session) -> list[dict]:
    url, api_key = get_effective_config(db)
    if not api_key:
        raise _ConfigError("SYNCTHING_API_KEY not configured")
    headers = {"X-API-Key": api_key}

    async with httpx.AsyncClient(timeout=5.0) as client:
        folders_resp = await client.get(f"{url}/rest/config/folders", headers=headers)
        folders_resp.raise_for_status()
        folders_data = folders_resp.json() or []

        completion_resps = await asyncio.gather(
            *[
                client.get(
                    f"{url}/rest/db/completion",
                    headers=headers,
                    params={"folder": f.get("id")},
                )
                for f in folders_data
            ],
            return_exceptions=True,
        )

    result = []
    for f, comp_resp in zip(folders_data, completion_resps):
        comp = {}
        if not isinstance(comp_resp, Exception) and comp_resp.status_code == 200:
            comp = comp_resp.json()
        need_bytes = comp.get("needBytes", 0)
        global_bytes = comp.get("globalBytes", 0)
        result.append({
            "id": f.get("id"),
            "label": f.get("label"),
            "path": f.get("path"),
            "type": f.get("type"),
            "paused": f.get("paused", False),
            "completion_pct": comp.get("completion", 100 if not comp else 0),
            "need_bytes": need_bytes,
            "need_bytes_fmt": _fmt_bytes(need_bytes),
            "global_bytes": global_bytes,
            "global_bytes_fmt": _fmt_bytes(global_bytes),
            "need_items": comp.get("needItems", 0),
        })
    return result


async def list_devices(db: Session) -> list[dict]:
    url, api_key = get_effective_config(db)
    if not api_key:
        raise _ConfigError("SYNCTHING_API_KEY not configured")
    headers = {"X-API-Key": api_key}

    async with httpx.AsyncClient(timeout=5.0) as client:
        devices_resp, conns_resp = await asyncio.gather(
            client.get(f"{url}/rest/config/devices", headers=headers),
            client.get(f"{url}/rest/system/connections", headers=headers),
        )
        devices_resp.raise_for_status()
        devices_data = devices_resp.json() or []
        conns = conns_resp.json().get("connections", {}) if conns_resp.status_code == 200 else {}

    return [
        {
            "device_id": d.get("deviceID"),
            "name": d.get("name"),
            "addresses": d.get("addresses", []),
            "paused": d.get("paused", False),
            "connected": conns.get(d.get("deviceID"), {}).get("connected", False),
            "address": conns.get(d.get("deviceID"), {}).get("address"),
            "last_seen": conns.get(d.get("deviceID"), {}).get("lastSeen"),
            "client_version": conns.get(d.get("deviceID"), {}).get("clientVersion"),
        }
        for d in devices_data
    ]


async def rescan_folder(db: Session, folder_id: str) -> dict:
    return await _proxy_post(db, "/rest/db/scan", params={"folder": folder_id})


class _ConfigError(Exception):
    pass
