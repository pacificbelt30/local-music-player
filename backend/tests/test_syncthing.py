"""Tests for Syncthing config + proxy API."""
from unittest.mock import AsyncMock, patch

from app.models import AppSetting


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


# ── GET /syncthing/status ────────────────────────────────────────────────────

def test_status_unconfigured_when_no_api_key(client):
    data = client.get("/api/v1/syncthing/status").json()
    assert data["available"] is False
    assert "SYNCTHING_API_KEY" in data["reason"]


# ── GET /syncthing/folders ────────────────────────────────────────────────────

def test_folders_requires_api_key(client):
    resp = client.get("/api/v1/syncthing/folders")
    assert resp.status_code == 400


def test_folders_proxies_syncthing(client, db):
    db.add(AppSetting(key="syncthing_api_key", value="k"))
    db.commit()

    fake = AsyncMock(return_value=[
        {"id": "music", "label": "Music", "path": "/data/music", "type": "sendreceive", "paused": False},
    ])
    with patch("app.services.syncthing_service._proxy_get", fake):
        resp = client.get("/api/v1/syncthing/folders")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "music"
    assert data[0]["label"] == "Music"


# ── GET /syncthing/devices ────────────────────────────────────────────────────

def test_devices_proxies_syncthing(client, db):
    db.add(AppSetting(key="syncthing_api_key", value="k"))
    db.commit()

    fake = AsyncMock(return_value=[
        {"deviceID": "ABCDEFG-HIJKLMN", "name": "Phone", "addresses": ["dynamic"], "paused": False},
    ])
    with patch("app.services.syncthing_service._proxy_get", fake):
        resp = client.get("/api/v1/syncthing/devices")
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["device_id"] == "ABCDEFG-HIJKLMN"
    assert data[0]["name"] == "Phone"


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
