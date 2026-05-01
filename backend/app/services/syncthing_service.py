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


async def get_syncthing_status(db: Session) -> dict:
    """Fetch Syncthing folder status from its REST API."""
    url, api_key = get_effective_config(db)
    if not api_key:
        return {"available": False, "reason": "SYNCTHING_API_KEY not configured"}

    headers = {"X-API-Key": api_key}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{url}/rest/system/status", headers=headers)
            resp.raise_for_status()
            system = resp.json()

            folders_resp = await client.get(f"{url}/rest/db/completion", headers=headers)
            completion = folders_resp.json() if folders_resp.status_code == 200 else {}

        return {
            "available": True,
            "my_id": system.get("myID"),
            "completion_pct": completion.get("completion", 0),
            "syncing": completion.get("globalBytes", 0) != completion.get("localBytes", 0),
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
    data = await _proxy_get(db, "/rest/config/folders")
    return [
        {
            "id": f.get("id"),
            "label": f.get("label"),
            "path": f.get("path"),
            "type": f.get("type"),
            "paused": f.get("paused", False),
        }
        for f in (data or [])
    ]


async def list_devices(db: Session) -> list[dict]:
    data = await _proxy_get(db, "/rest/config/devices")
    return [
        {
            "device_id": d.get("deviceID"),
            "name": d.get("name"),
            "addresses": d.get("addresses", []),
            "paused": d.get("paused", False),
        }
        for d in (data or [])
    ]


async def rescan_folder(db: Session, folder_id: str) -> dict:
    return await _proxy_post(db, "/rest/db/scan", params={"folder": folder_id})


class _ConfigError(Exception):
    pass
