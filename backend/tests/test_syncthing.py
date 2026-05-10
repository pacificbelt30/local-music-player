"""Tests for Syncthing config + proxy API."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.models import AppSetting
from app.services.syncthing_service import _fmt_bytes


# ── Helpers ───────────────────────────────────────────────────────────────────

class _MockResponse:
    def __init__(self, status_code: int, data):
        self.status_code = status_code
        self._data = data

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error", request=MagicMock(), response=MagicMock(status_code=self.status_code)
            )


def _make_client_mock(url_responses: dict):
    """
    Build a mock httpx.AsyncClient whose .get() dispatches based on URL substring.
    url_responses: {url_substring: (status_code, data)}
    """
    async def fake_get(url, **kwargs):
        for pattern, (status, data) in url_responses.items():
            if pattern in url:
                return _MockResponse(status, data)
        return _MockResponse(404, {"error": f"no mock for {url}"})

    mock = MagicMock()
    mock.get = fake_get
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=None)
    return mock


# ── _fmt_bytes ────────────────────────────────────────────────────────────────

def test_fmt_bytes_bytes():
    assert _fmt_bytes(512) == "512.0 B"

def test_fmt_bytes_kilobytes():
    assert _fmt_bytes(1024) == "1.0 KB"

def test_fmt_bytes_megabytes():
    assert _fmt_bytes(1024 * 1024) == "1.0 MB"

def test_fmt_bytes_gigabytes():
    assert _fmt_bytes(1024 ** 3) == "1.0 GB"

def test_fmt_bytes_terabytes():
    assert _fmt_bytes(1024 ** 4) == "1.0 TB"

def test_fmt_bytes_zero():
    assert _fmt_bytes(0) == "0.0 B"


# ── GET /syncthing/config ─────────────────────────────────────────────────────

def test_get_config_defaults_from_env(client):
    resp = client.get("/api/v1/syncthing/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "url" in data
    assert data["api_key_set"] is False  # env default is empty


def test_get_config_reflects_db_overrides(client, db):
    db.add(AppSetting(key="syncthing_url", value="http://stng:8384"))
    db.add(AppSetting(key="syncthing_api_key", value="secret"))
    db.commit()

    data = client.get("/api/v1/syncthing/config").json()
    assert data["url"] == "http://stng:8384"
    assert data["api_key_set"] is True


def test_get_config_does_not_leak_api_key(client, db):
    db.add(AppSetting(key="syncthing_api_key", value="topsecret"))
    db.commit()

    body = client.get("/api/v1/syncthing/config").text
    assert "topsecret" not in body


# ── PATCH /syncthing/config ───────────────────────────────────────────────────

def test_update_url_persists(client):
    resp = client.patch("/api/v1/syncthing/config", json={"url": "http://example:8384"})
    assert resp.status_code == 200
    assert resp.json()["url"] == "http://example:8384"
    assert client.get("/api/v1/syncthing/config").json()["url"] == "http://example:8384"


def test_update_api_key_marks_as_set(client):
    resp = client.patch("/api/v1/syncthing/config", json={"api_key": "newkey"})
    assert resp.status_code == 200
    assert resp.json()["api_key_set"] is True


def test_partial_update_leaves_other_unchanged(client, db):
    db.add(AppSetting(key="syncthing_url", value="http://a:8384"))
    db.add(AppSetting(key="syncthing_api_key", value="originalkey"))
    db.commit()

    client.patch("/api/v1/syncthing/config", json={"url": "http://b:8384"})
    assert db.get(AppSetting, "syncthing_api_key").value == "originalkey"


# ── GET /syncthing/status ─────────────────────────────────────────────────────

def test_status_unconfigured_when_no_api_key(client):
    data = client.get("/api/v1/syncthing/status").json()
    assert data["available"] is False
    assert "SYNCTHING_API_KEY" in data["reason"]


def test_status_returns_detailed_fields(client, db):
    db.add(AppSetting(key="syncthing_api_key", value="k"))
    db.commit()

    mock = _make_client_mock({
        "/rest/system/status": (200, {"myID": "AAAAAAA-BBBBBBB"}),
        "/rest/db/completion": (200, {
            "completion": 85.5,
            "needBytes": 1024 * 1024,
            "globalBytes": 10 * 1024 * 1024,
            "needItems": 3,
        }),
        "/rest/system/connections": (200, {
            "connections": {
                "DEV-A": {"connected": True},
                "DEV-B": {"connected": False},
            }
        }),
    })
    with patch("app.services.syncthing_service.httpx.AsyncClient", return_value=mock):
        data = client.get("/api/v1/syncthing/status").json()

    assert data["available"] is True
    assert data["my_id"] == "AAAAAAA-BBBBBBB"
    assert data["completion_pct"] == pytest.approx(85.5)
    assert data["syncing"] is True
    assert data["need_bytes"] == 1024 * 1024
    assert data["need_bytes_fmt"] == "1.0 MB"
    assert data["global_bytes"] == 10 * 1024 * 1024
    assert data["global_bytes_fmt"] == "10.0 MB"
    assert data["need_items"] == 3
    assert data["connected_devices"] == 1
    assert data["total_devices"] == 2


def test_status_not_syncing_when_need_bytes_zero(client, db):
    db.add(AppSetting(key="syncthing_api_key", value="k"))
    db.commit()

    mock = _make_client_mock({
        "/rest/system/status": (200, {"myID": "X"}),
        "/rest/db/completion": (200, {"completion": 100.0, "needBytes": 0, "globalBytes": 512, "needItems": 0}),
        "/rest/system/connections": (200, {"connections": {}}),
    })
    with patch("app.services.syncthing_service.httpx.AsyncClient", return_value=mock):
        data = client.get("/api/v1/syncthing/status").json()

    assert data["available"] is True
    assert data["syncing"] is False
    assert data["need_bytes"] == 0
    assert data["connected_devices"] == 0


def test_status_unreachable_returns_available_false(client, db):
    db.add(AppSetting(key="syncthing_api_key", value="k"))
    db.commit()

    mock = MagicMock()
    mock.__aenter__ = AsyncMock(side_effect=httpx.ConnectError("refused"))
    mock.__aexit__ = AsyncMock(return_value=None)
    with patch("app.services.syncthing_service.httpx.AsyncClient", return_value=mock):
        data = client.get("/api/v1/syncthing/status").json()

    assert data["available"] is False
    assert "not reachable" in data["reason"]


def test_status_http_error_returns_available_false(client, db):
    db.add(AppSetting(key="syncthing_api_key", value="k"))
    db.commit()

    async def fake_get(url, **kwargs):
        resp = MagicMock(status_code=403)
        raise httpx.HTTPStatusError("forbidden", request=MagicMock(), response=resp)

    mock = MagicMock()
    mock.get = fake_get
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=None)
    with patch("app.services.syncthing_service.httpx.AsyncClient", return_value=mock):
        data = client.get("/api/v1/syncthing/status").json()

    assert data["available"] is False
    assert "403" in data["reason"]


# ── GET /syncthing/folders ────────────────────────────────────────────────────

def test_folders_requires_api_key(client):
    resp = client.get("/api/v1/syncthing/folders")
    assert resp.status_code == 400


def test_folders_proxies_syncthing(client, db):
    db.add(AppSetting(key="syncthing_api_key", value="k"))
    db.commit()

    mock = _make_client_mock({
        "/rest/config/folders": (200, [
            {"id": "music", "label": "Music", "path": "/data/music", "type": "sendreceive", "paused": False},
        ]),
        "/rest/db/completion": (200, {
            "completion": 100.0, "needBytes": 0, "globalBytes": 2048, "needItems": 0,
        }),
    })
    with patch("app.services.syncthing_service.httpx.AsyncClient", return_value=mock):
        resp = client.get("/api/v1/syncthing/folders")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "music"
    assert data[0]["label"] == "Music"


def test_folders_includes_completion_fields(client, db):
    db.add(AppSetting(key="syncthing_api_key", value="k"))
    db.commit()

    mock = _make_client_mock({
        "/rest/config/folders": (200, [
            {"id": "music", "label": "Music", "path": "/data", "type": "sendreceive", "paused": False},
        ]),
        "/rest/db/completion": (200, {
            "completion": 60.0,
            "needBytes": 512 * 1024,
            "globalBytes": 1024 * 1024,
            "needItems": 5,
        }),
    })
    with patch("app.services.syncthing_service.httpx.AsyncClient", return_value=mock):
        data = client.get("/api/v1/syncthing/folders").json()

    assert data[0]["completion_pct"] == pytest.approx(60.0)
    assert data[0]["need_bytes"] == 512 * 1024
    assert data[0]["need_bytes_fmt"] == "512.0 KB"
    assert data[0]["global_bytes"] == 1024 * 1024
    assert data[0]["global_bytes_fmt"] == "1.0 MB"
    assert data[0]["need_items"] == 5


def test_folders_completion_error_falls_back_gracefully(client, db):
    """Completion API failure should not crash; folder is returned with zeroed fields."""
    db.add(AppSetting(key="syncthing_api_key", value="k"))
    db.commit()

    async def fake_get(url, **kwargs):
        if "/rest/config/folders" in url:
            return _MockResponse(200, [
                {"id": "music", "label": "Music", "path": "/data", "type": "sendreceive", "paused": False},
            ])
        # Completion endpoint returns error
        return _MockResponse(503, {})

    mock = MagicMock()
    mock.get = fake_get
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=None)
    with patch("app.services.syncthing_service.httpx.AsyncClient", return_value=mock):
        resp = client.get("/api/v1/syncthing/folders")

    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["id"] == "music"
    assert data[0]["need_bytes"] == 0
    assert data[0]["global_bytes"] == 0


def test_folders_empty_list(client, db):
    db.add(AppSetting(key="syncthing_api_key", value="k"))
    db.commit()

    mock = _make_client_mock({
        "/rest/config/folders": (200, []),
    })
    with patch("app.services.syncthing_service.httpx.AsyncClient", return_value=mock):
        resp = client.get("/api/v1/syncthing/folders")

    assert resp.status_code == 200
    assert resp.json() == []


# ── GET /syncthing/devices ────────────────────────────────────────────────────

def test_devices_requires_api_key(client):
    resp = client.get("/api/v1/syncthing/devices")
    assert resp.status_code == 400


def test_devices_proxies_syncthing(client, db):
    db.add(AppSetting(key="syncthing_api_key", value="k"))
    db.commit()

    mock = _make_client_mock({
        "/rest/config/devices": (200, [
            {"deviceID": "ABCDEFG-HIJKLMN", "name": "Phone", "addresses": ["dynamic"], "paused": False},
        ]),
        "/rest/system/connections": (200, {"connections": {}}),
    })
    with patch("app.services.syncthing_service.httpx.AsyncClient", return_value=mock):
        resp = client.get("/api/v1/syncthing/devices")

    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["device_id"] == "ABCDEFG-HIJKLMN"
    assert data[0]["name"] == "Phone"


def test_devices_includes_connection_status(client, db):
    db.add(AppSetting(key="syncthing_api_key", value="k"))
    db.commit()

    mock = _make_client_mock({
        "/rest/config/devices": (200, [
            {"deviceID": "DEV-AAA", "name": "Laptop", "addresses": [], "paused": False},
            {"deviceID": "DEV-BBB", "name": "Server", "addresses": [], "paused": False},
        ]),
        "/rest/system/connections": (200, {
            "connections": {
                "DEV-AAA": {
                    "connected": True,
                    "address": "192.168.1.10:22000",
                    "clientVersion": "v1.27.0",
                    "lastSeen": "2026-04-30T10:00:00Z",
                },
                "DEV-BBB": {
                    "connected": False,
                    "address": None,
                    "clientVersion": None,
                    "lastSeen": "2026-04-01T00:00:00Z",
                },
            }
        }),
    })
    with patch("app.services.syncthing_service.httpx.AsyncClient", return_value=mock):
        data = client.get("/api/v1/syncthing/devices").json()

    laptop = next(d for d in data if d["device_id"] == "DEV-AAA")
    assert laptop["connected"] is True
    assert laptop["address"] == "192.168.1.10:22000"
    assert laptop["client_version"] == "v1.27.0"

    server = next(d for d in data if d["device_id"] == "DEV-BBB")
    assert server["connected"] is False
    assert server["last_seen"] == "2026-04-01T00:00:00Z"


def test_devices_disconnected_shows_last_seen(client, db):
    db.add(AppSetting(key="syncthing_api_key", value="k"))
    db.commit()

    mock = _make_client_mock({
        "/rest/config/devices": (200, [
            {"deviceID": "DEV-X", "name": "Old", "addresses": [], "paused": False},
        ]),
        "/rest/system/connections": (200, {
            "connections": {
                "DEV-X": {"connected": False, "lastSeen": "2026-03-15T08:30:00Z"},
            }
        }),
    })
    with patch("app.services.syncthing_service.httpx.AsyncClient", return_value=mock):
        data = client.get("/api/v1/syncthing/devices").json()

    assert data[0]["connected"] is False
    assert data[0]["last_seen"] == "2026-03-15T08:30:00Z"


def test_devices_empty_list(client, db):
    db.add(AppSetting(key="syncthing_api_key", value="k"))
    db.commit()

    mock = _make_client_mock({
        "/rest/config/devices": (200, []),
        "/rest/system/connections": (200, {"connections": {}}),
    })
    with patch("app.services.syncthing_service.httpx.AsyncClient", return_value=mock):
        resp = client.get("/api/v1/syncthing/devices")

    assert resp.status_code == 200
    assert resp.json() == []


# ── POST /syncthing/folders/{id}/rescan ───────────────────────────────────────

def test_rescan_folder_calls_post(client, db):
    db.add(AppSetting(key="syncthing_api_key", value="k"))
    db.commit()

    fake = AsyncMock(return_value={"ok": True})
    with patch("app.services.syncthing_service._proxy_post", fake):
        resp = client.post("/api/v1/syncthing/folders/music/rescan")
    assert resp.status_code == 200
    fake.assert_awaited_once()
    args, kwargs = fake.call_args
    assert args[1] == "/rest/db/scan"
    assert kwargs["params"] == {"folder": "music"}


# ── POST /syncthing/config/test ───────────────────────────────────────────────

def test_config_test_rejects_empty_key(client):
    resp = client.post("/api/v1/syncthing/config/test", json={"url": "http://x:8384", "api_key": ""})
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
