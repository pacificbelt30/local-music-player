import httpx

from app.config import settings


async def get_syncthing_status() -> dict:
    """Fetch Syncthing folder status from its REST API."""
    if not settings.syncthing_api_key:
        return {"available": False, "reason": "SYNCTHING_API_KEY not configured"}

    headers = {"X-API-Key": settings.syncthing_api_key}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.syncthing_url}/rest/system/status", headers=headers)
            resp.raise_for_status()
            system = resp.json()

            folders_resp = await client.get(f"{settings.syncthing_url}/rest/db/completion", headers=headers)
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
