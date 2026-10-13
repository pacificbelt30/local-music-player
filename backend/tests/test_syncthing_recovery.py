"""Regression tests for restart recovery and truthful synchronization state."""
from unittest.mock import patch

import httpx
import pytest

from app.models import AppSetting
from app.services import syncthing_service as service

RealClient = httpx.AsyncClient


@pytest.fixture
def upstream(db, monkeypatch):
    db.add(AppSetting(key="syncthing_api_key", value="test-key"))
    db.commit()
    responses = {
        "/rest/system/status": {"myID": "LOCAL"},
        "/rest/config/folders": [{"id": "music", "label": "Music", "path": "/var/syncthing/downloads",
                                  "devices": [{"deviceID": "LOCAL"}, {"deviceID": "PHONE"}]}],
        "/rest/config/devices": [{"deviceID": "LOCAL"}, {"deviceID": "PHONE", "name": "Phone"}],
        "/rest/system/connections": {"connections": {"PHONE": {"connected": True}}},
        "/rest/db/status": {"state": "idle", "globalBytes": 1000, "needBytes": 0, "needTotalItems": 0},
        "/rest/db/completion": {"remoteState": "valid", "completion": 100, "globalBytes": 1000,
                                "needBytes": 0, "needItems": 0, "needDeletes": 0},
        "/rest/stats/device": {"PHONE": {"lastSeen": "2026-10-13T00:00:00Z"}},
    }
    calls = []

    def handle(request):
        calls.append(request)
        value = responses.get(request.url.path, {})
        if callable(value):
            value = value(request)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, httpx.Response):
            return value
        return httpx.Response(200, json=value)

    monkeypatch.setattr(service, "_client", lambda url: RealClient(transport=httpx.MockTransport(handle), trust_env=False))
    return responses, calls


def status(client):
    response = client.get("/api/v1/syncthing/status")
    assert response.status_code == 200
    return response.json()


def test_queries_each_folder_and_remote_device_and_filters_self(client, upstream):
    _, calls = upstream
    result = status(client)
    assert result["state"] == "synced" and result["completion_pct"] == 100
    assert result["total_devices"] == result["connected_devices"] == 1
    completions = [r for r in calls if r.url.path == "/rest/db/completion"]
    assert len(completions) == 1
    assert dict(completions[0].url.params) == {"folder": "music", "device": "PHONE"}
    assert all(r.headers["X-API-Key"] == "test-key" for r in calls)


def test_folder_missing_after_recreation_reports_error(client, upstream):
    responses, _ = upstream
    responses["/rest/db/status"]["state"] = "error"
    responses["/rest/db/status"]["error"] = "folder path missing"
    result = status(client)
    assert result["available"] is True
    assert result["state"] == "error"
    assert "folder path missing" in " ".join(result["errors"])
    folder = client.get("/api/v1/syncthing/folders").json()[0]
    assert folder["state"] == "error"


def test_disconnected_peer_is_not_synced_even_when_cached_completion_is_100(client, upstream):
    responses, _ = upstream
    responses["/rest/system/connections"]["connections"]["PHONE"]["connected"] = False
    result = status(client)
    assert result["state"] == "disconnected"
    assert result["connected_devices"] == 0


def test_successful_poll_recovers_after_peer_reconnects(client, upstream):
    responses, _ = upstream
    connection = responses["/rest/system/connections"]["connections"]["PHONE"]
    connection["connected"] = False
    assert status(client)["state"] == "disconnected"
    connection["connected"] = True
    assert status(client)["state"] == "synced"


def test_remote_download_backlog_is_counted_when_local_is_complete(client, upstream):
    responses, _ = upstream
    responses["/rest/db/completion"].update(completion=60, needBytes=400, needItems=2)
    result = status(client)
    assert result["state"] == "syncing"
    assert result["completion_pct"] == 60
    assert result["need_bytes"] == 400 and result["need_items"] == 2


def test_pending_deletions_are_syncing_with_zero_needed_bytes(client, upstream):
    responses, _ = upstream
    responses["/rest/db/completion"]["needDeletes"] = 2
    result = status(client)
    assert result["state"] == "syncing"
    assert result["need_bytes"] == 0 and result["need_items"] == 2


def test_local_pending_items_and_remote_pending_items_are_both_counted(client, upstream):
    responses, _ = upstream
    responses["/rest/db/status"].update(needBytes=100, needTotalItems=1)
    responses["/rest/db/completion"].update(completion=80, needBytes=200, needItems=2)
    result = status(client)
    assert result["need_bytes"] == 300 and result["need_items"] == 3
    assert result["global_bytes"] == 1000


def test_completion_api_failure_reports_unknown_instead_of_100(client, upstream):
    responses, _ = upstream
    responses["/rest/db/completion"] = httpx.Response(503)
    result = status(client)
    assert result["available"] is True
    assert result["state"] == "unknown" and result["completion_pct"] is None
    folder = client.get("/api/v1/syncthing/folders").json()[0]
    assert folder["state"] == "unknown" and folder["completion_pct"] is None


def test_unknown_remote_index_is_not_synced(client, upstream):
    responses, _ = upstream
    responses["/rest/db/completion"]["remoteState"] = "unknown"
    assert status(client)["state"] == "unknown"


def test_malformed_local_status_is_not_synced(client, upstream):
    responses, _ = upstream
    responses["/rest/db/status"] = {}
    result = status(client)
    assert result["state"] == "unknown" and result["completion_pct"] is None


@pytest.mark.parametrize("kind", [httpx.ReadError, httpx.RemoteProtocolError, httpx.ConnectError])
def test_transient_restart_error_retries_read_and_recovers(client, upstream, kind):
    responses, calls = upstream
    original = responses["/rest/system/status"]
    def restarting(request):
        if sum(r.url.path == request.url.path for r in calls) == 1:
            return kind("connection closed")
        return original
    responses["/rest/system/status"] = restarting
    assert status(client)["state"] == "synced"
    assert sum(r.url.path == "/rest/system/status" for r in calls) == 2


def test_persistent_read_error_returns_unavailable_without_500(client, upstream):
    responses, calls = upstream
    responses["/rest/system/status"] = httpx.ReadError("connection closed")
    result = status(client)
    assert result["available"] is False
    assert sum(r.url.path == "/rest/system/status" for r in calls) == 2


def test_bad_api_key_does_not_retry_or_erase_saved_key(client, upstream, db):
    responses, calls = upstream
    responses["/rest/system/status"] = httpx.Response(403)
    result = status(client)
    assert result["available"] is False and "403" in result["reason"]
    assert len(calls) == 1
    assert db.get(AppSetting, "syncthing_api_key").value == "test-key"


def test_device_list_excludes_self_and_uses_device_stats(client, upstream):
    devices = client.get("/api/v1/syncthing/devices").json()
    assert len(devices) == 1 and devices[0]["device_id"] == "PHONE"
    assert devices[0]["last_seen"] == "2026-10-13T00:00:00Z"


def test_device_connection_api_failure_is_explicit(client, upstream):
    responses, _ = upstream
    responses["/rest/system/connections"] = httpx.ReadError("closed")
    assert status(client)["state"] == "unknown"
    device = client.get("/api/v1/syncthing/devices").json()[0]
    assert device["connection_known"] is False


def test_malformed_connection_response_is_unknown(client, upstream):
    responses, _ = upstream
    responses["/rest/system/connections"] = {}
    assert status(client)["state"] == "unknown"
    assert client.get("/api/v1/syncthing/devices").json()[0]["connection_known"] is False


def test_multiple_folders_use_distinct_ids_and_sum_sizes(client, upstream):
    responses, calls = upstream
    responses["/rest/config/folders"].append({"id": "video", "devices": [{"deviceID": "PHONE"}]})
    def local(request):
        size = 1000 if request.url.params["folder"] == "music" else 2000
        return {"state": "idle", "globalBytes": size, "needBytes": 0, "needTotalItems": 0}
    def remote(request):
        size = 1000 if request.url.params["folder"] == "music" else 2000
        return {"remoteState": "valid", "completion": 100, "globalBytes": size, "needBytes": 0, "needItems": 0}
    responses["/rest/db/status"] = local
    responses["/rest/db/completion"] = remote
    result = status(client)
    assert result["global_bytes"] == 3000 and result["total_devices"] == 1
    assert {r.url.params["folder"] for r in calls if r.url.path == "/rest/db/completion"} == {"music", "video"}


def test_connection_test_uses_entered_url_with_saved_key(client, upstream, db):
    _, calls = upstream
    db.add(AppSetting(key="syncthing_url", value="http://old-container:8384"))
    db.commit()
    result = client.post("/api/v1/syncthing/config/test", json={"url": "http://new-container:8384"}).json()
    assert result["ok"] is True
    assert calls[0].url.host == "new-container"
    assert calls[0].headers["X-API-Key"] == "test-key"
    assert db.get(AppSetting, "syncthing_url").value == "http://old-container:8384"


def test_reset_saved_container_ip_and_key_to_environment(client, upstream, monkeypatch):
    monkeypatch.setattr(service.settings, "syncthing_url", "http://syncthing:8384")
    monkeypatch.setattr(service.settings, "syncthing_api_key", "env-key")
    client.patch("/api/v1/syncthing/config", json={"url": "http://172.20.0.2:8384", "api_key": "stale-key"})
    response = client.patch("/api/v1/syncthing/config", json={"url": "", "api_key": ""}).json()
    assert response["url"] == response["default_url"] == "http://syncthing:8384"
    assert response["api_key_set"] and not response["overridden"]
    assert "env-key" not in str(response)


def test_rescan_post_is_not_retried_on_disconnect(client, upstream):
    responses, calls = upstream
    responses["/rest/db/scan"] = httpx.ReadError("closed")
    assert client.post("/api/v1/syncthing/folders/music/rescan").status_code == 502
    assert len(calls) == 1


@pytest.mark.parametrize("url,trust_env", [
    ("http://syncthing:8384", False), ("http://localhost:8384", False),
    ("http://192.168.1.5:8384", False), ("http://[::1]:8384", False),
    ("https://sync.example.com", True),
])
def test_internal_services_bypass_environment_proxy_only(url, trust_env):
    with patch.object(service.httpx, "AsyncClient") as constructor:
        service._client(url)
    assert constructor.call_args.kwargs["trust_env"] is trust_env


@pytest.mark.parametrize("paused,peers,expected", [(True, True, "paused"), (False, False, "unshared")])
def test_paused_or_unshared_folder_is_not_synced(client, upstream, paused, peers, expected):
    responses, _ = upstream
    folder = responses["/rest/config/folders"][0]
    folder["paused"] = paused
    if not peers:
        folder["devices"] = [{"deviceID": "LOCAL"}]
    assert status(client)["state"] == expected


def test_no_shared_folders_is_not_synced(client, upstream):
    responses, _ = upstream
    responses["/rest/config/folders"] = []
    result = status(client)
    assert result["state"] == "unshared" and result["completion_pct"] is None
