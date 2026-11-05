"""Optional providers, secret persistence, bounded reads and safe failures."""

from datetime import datetime, timedelta, timezone
import json
import logging
from unittest.mock import MagicMock

import httpx
import pytest

from app.config import settings
from app.models import AppSetting
from app.services import discovery
from app.services.discovery_config import (
    ConfigUpdate,
    api_key,
    read_config,
    update_config,
)

YT = {
    "items": [
        {
            "id": "jNQXAC9IVRw",
            "snippet": {"title": "Me at the zoo", "channelTitle": "jawed"},
        }
    ]
}
FM = {
    "toptracks": {
        "track": [
            {"name": "Song", "artist": {"name": "Artist"}, "@attr": {"rank": "1"}}
        ]
    }
}


@pytest.fixture(autouse=True)
def providers(monkeypatch):
    clock = [datetime(2026, 11, 5, 12, tzinfo=timezone.utc)]
    monkeypatch.setattr(discovery, "now", lambda: clock[0])
    lock = MagicMock()
    lock.acquire.return_value = lock.owned.return_value = True
    monkeypatch.setattr(discovery._redis, "lock", lambda *a, **kw: lock)
    external = MagicMock(
        side_effect=lambda provider, *a, **kw: (YT if provider == "youtube" else FM, {})
    )
    monkeypatch.setattr(discovery, "_request", external)
    return clock, lock, external


def configure(client, provider="youtube", **extra):
    return client.patch(
        "/api/v1/discovery/config/" + provider,
        json={"api_key": "test-secret-" + provider, "enabled": True, **extra},
    )


def test_disabled_by_default_and_no_outbound_requests(client, providers):
    config = client.get("/api/v1/discovery/config")
    assert config.status_code == 200 and config.headers["cache-control"] == "no-store"
    assert all(
        not c["enabled"] and not c["api_key_set"] for c in config.json().values()
    )
    for provider in ("youtube", "lastfm"):
        assert (
            client.get("/api/v1/discovery/popular/" + provider).json()["state"]
            == "disabled"
        )
    providers[2].assert_not_called()
    assert not (settings.data_path / ".discovery-key").exists()


def test_credentials_are_encrypted_and_never_returned(client, db):
    response = configure(client)
    assert response.status_code == 200
    assert response.json()["api_key_set"] and response.json()["enabled"]
    assert "test-secret" not in response.text
    assert "test-secret" not in client.get("/api/v1/discovery/config").text
    assert all("test-secret" not in row.value for row in db.query(AppSetting).all())
    assert api_key(read_config(db, "youtube")) == "test-secret-youtube"
    assert (settings.data_path / ".discovery-key").stat().st_mode & 0o777 == 0o600


def test_blank_key_keeps_it_delete_disables_and_clears_cache(client, db):
    configure(client)
    assert client.get("/api/v1/discovery/popular/youtube").json()["items"]
    assert client.patch(
        "/api/v1/discovery/config/youtube", json={"api_key": "", "region": "US"}
    ).json()["api_key_set"]
    assert api_key(read_config(db, "youtube")) == "test-secret-youtube"
    assert client.patch(
        "/api/v1/discovery/config/youtube", json={"clear_key": True}
    ).json() == {
        "provider": "youtube",
        "enabled": False,
        "region": "US",
        "api_key_set": False,
    }
    assert (
        not db.query(AppSetting)
        .filter(AppSetting.key.like("discovery:cache:youtube:%"))
        .all()
    )
    assert client.get("/api/v1/discovery/popular/youtube").json()["state"] == "disabled"


def test_validation_and_missing_key_do_not_echo_inputs(client):
    assert (
        client.patch(
            "/api/v1/discovery/config/youtube", json={"enabled": True}
        ).status_code
        == 409
    )
    response = client.patch(
        "/api/v1/discovery/config/youtube",
        json={"api_key": "sensitive\nvalue", "region": "ZZ"},
    )
    assert response.status_code == 422 and "sensitive" not in response.text
    assert client.patch("/api/v1/discovery/config/unknown", json={}).status_code == 422


def test_both_providers_and_cache_are_independent(client, providers):
    configure(client)
    configure(client, "lastfm")
    youtube = client.get("/api/v1/discovery/popular/youtube").json()
    lastfm = client.get("/api/v1/discovery/popular/lastfm").json()
    assert youtube["items"][0]["youtube_id"] == "jNQXAC9IVRw"
    assert (
        youtube["items"][0]["artist_label"] == "投稿者"
        and youtube["items"][0]["rank"] is None
    )
    assert lastfm["items"][0]["rank"] == 1 and lastfm["items"][0]["artist"] == "Artist"
    assert client.get("/api/v1/discovery/popular/youtube").json()["cached"] is True
    assert providers[2].call_count == 2
    assert (
        client.patch(
            "/api/v1/discovery/config/lastfm", json={"enabled": False}
        ).status_code
        == 200
    )
    assert client.get("/api/v1/discovery/popular/youtube").json()["cached"] is True


def test_similar_search_only_sends_selected_artist_and_track(client, providers):
    configure(client, "lastfm")
    providers[2].return_value = (
        {"similartracks": {"track": FM["toptracks"]["track"]}},
        {},
    )
    providers[2].side_effect = None
    response = client.get(
        "/api/v1/discovery/similar/lastfm", params={"artist": "Artist", "track": "Song"}
    )
    assert response.status_code == 200 and response.json()["items"]
    assert providers[2].call_args.args[2:5] == ("JP", "similar", "Artist")
    assert providers[2].call_args.args[5] == "Song"
    assert (
        client.get("/api/v1/discovery/similar/lastfm?artist=+&track=Song").status_code
        == 422
    )
    assert (
        client.get("/api/v1/discovery/similar/lastfm?artist=Artist&track=").status_code
        == 422
    )


def test_stale_cache_survives_failure_but_not_past_24_hours(client, providers):
    configure(client)
    client.get("/api/v1/discovery/popular/youtube")
    providers[0][0] += timedelta(hours=7)
    providers[2].side_effect = discovery.DiscoveryError("unavailable", "通信できません")
    stale = client.get("/api/v1/discovery/popular/youtube").json()
    assert stale["state"] == "stale" and stale["items"]
    providers[0][0] += timedelta(hours=18)
    assert client.get("/api/v1/discovery/popular/youtube").json()["items"] == []


def test_config_change_during_fetch_cannot_publish_stale_results(client, db, providers):
    configure(client)

    def changed(*args):
        update_config(db, "youtube", ConfigUpdate(enabled=False))
        return YT, {}

    providers[2].side_effect = changed
    result = client.get("/api/v1/discovery/popular/youtube").json()
    assert result["state"] == "settings_changed" and not result["items"]
    assert (
        not db.query(AppSetting)
        .filter(AppSetting.key.like("discovery:cache:youtube:%"))
        .all()
    )


def test_daily_budget_persists_and_forced_refresh_cannot_bypass_it(
    client, db, providers
):
    configure(client)
    db.add(AppSetting(key="discovery:usage:youtube:2026-11-05", value="100"))
    db.commit()
    result = client.get("/api/v1/discovery/popular/youtube?refresh=true").json()
    assert result["error_code"] == "daily_budget"
    providers[2].assert_not_called()


def test_test_connection_is_explicit_works_while_disabled_and_uses_budget(
    client, db, providers
):
    configure(client, enabled=False)
    result = client.post("/api/v1/discovery/config/youtube/test").json()
    assert result["state"] == "ready" and "test-secret" not in json.dumps(result)
    assert not client.get("/api/v1/discovery/config").json()["youtube"]["enabled"]
    assert db.get(AppSetting, "discovery:usage:youtube:2026-11-05").value == "1"
    assert (
        client.post("/api/v1/discovery/config/youtube/test").json()["error_code"]
        == "cooldown"
    )


def test_lost_encryption_key_is_actionable_without_outbound_access(client, providers):
    configure(client)
    (settings.data_path / ".discovery-key").unlink()
    result = client.get("/api/v1/discovery/popular/youtube").json()
    assert result[
        "error_code"
    ] == "key_unavailable" and "test-secret" not in json.dumps(result)
    providers[2].assert_not_called()


def test_inflight_requests_are_not_duplicated(client, providers):
    configure(client)
    providers[1].acquire.return_value = False
    assert (
        client.get("/api/v1/discovery/popular/youtube").json()["error_code"]
        == "refreshing"
    )
    providers[2].assert_not_called()


def test_upstream_cache_headers_are_respected(client, db, providers):
    configure(client, "lastfm")
    providers[2].side_effect = None
    providers[2].return_value = (FM, {"cache-control": "no-store"})
    assert client.get("/api/v1/discovery/popular/lastfm").json()["items"]
    assert (
        not db.query(AppSetting)
        .filter(AppSetting.key.like("discovery:cache:lastfm:%"))
        .all()
    )
    providers[0][0] += timedelta(seconds=3)
    providers[2].return_value = (FM, {"cache-control": "max-age=60"})
    client.get("/api/v1/discovery/popular/lastfm")
    providers[0][0] += timedelta(seconds=61)
    providers[2].side_effect = discovery.DiscoveryError("unavailable", "offline")
    assert client.get("/api/v1/discovery/popular/lastfm").json()["items"] == []


def test_malformed_refresh_does_not_destroy_a_successful_cache(client, providers):
    configure(client)
    client.get("/api/v1/discovery/popular/youtube")
    providers[0][0] += timedelta(seconds=3)
    providers[2].side_effect = None
    providers[2].return_value = ({"unknown": []}, {})
    result = client.get("/api/v1/discovery/popular/youtube?refresh=true").json()
    assert result["state"] == "stale" and result["items"][0]["title"] == "Me at the zoo"


def test_expired_lease_refuses_to_publish(client, providers):
    configure(client)
    providers[1].owned.return_value = False
    assert (
        client.get("/api/v1/discovery/popular/youtube").json()["error_code"]
        == "settings_changed"
    )


def test_cache_maintenance_expires_data_without_deleting_credentials(
    client, db, providers
):
    configure(client)
    client.get("/api/v1/discovery/popular/youtube")
    db.add(AppSetting(key="discovery:usage:youtube:2026-10-01", value="1"))
    db.commit()
    providers[0][0] += timedelta(hours=25)
    assert discovery.purge_expired(db) == 1
    assert db.get(AppSetting, "discovery:usage:youtube:2026-10-01") is None
    assert api_key(read_config(db, "youtube")) == "test-secret-youtube"
    assert db.get(AppSetting, "discovery:usage:youtube:2026-11-05").value == "1"


def test_lastfm_cache_age_does_not_extend_the_upstream_expiration(client, providers):
    configure(client, "lastfm")
    providers[2].side_effect = None
    providers[2].return_value = (FM, {"cache-control": "max-age=60", "age": "58"})
    first = client.get("/api/v1/discovery/popular/lastfm").json()
    assert datetime.fromisoformat(first["expires_at"]) == providers[0][0] + timedelta(
        seconds=2
    )
    providers[0][0] += timedelta(seconds=3)
    providers[2].side_effect = discovery.DiscoveryError("unavailable", "offline")
    assert client.get("/api/v1/discovery/popular/lastfm").json()["items"] == []


def test_connection_check_rejects_changed_response_shapes(client, providers):
    configure(client)
    providers[2].side_effect = None
    providers[2].return_value = ({"unexpected": []}, {})
    result = client.post("/api/v1/discovery/config/youtube/test").json()
    assert result["state"] == "error" and result["error_code"] == "invalid_response"


@pytest.mark.parametrize(
    "provider,status,data,expected",
    [
        ("lastfm", 200, {"error": 10, "message": "secret-do-not-echo"}, "key_rejected"),
        ("lastfm", 200, {"error": 29}, "rate_limited"),
        (
            "youtube",
            403,
            {"error": {"errors": [{"reason": "quotaExceeded"}]}},
            "quota_exceeded",
        ),
        ("youtube", 400, {"error": {"message": "secret-do-not-echo"}}, "key_rejected"),
    ],
)
def test_http_contract_and_safe_provider_errors(
    monkeypatch, provider, status, data, expected, caplog
):
    real_client = httpx.Client
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, json=data)

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    # The autouse fixture replaces the public function; reload the original from
    # its stored MagicMock side effect would bypass real HTTP. Read a module-level
    # alias captured below for transport contract tests.
    with caplog.at_level(logging.INFO, logger="httpx"):
        with pytest.raises(discovery.DiscoveryError) as error:
            REAL_REQUEST(provider, "secret-do-not-echo", "JP", "popular")
    assert error.value.code == expected and "secret-do-not-echo" not in str(error.value)
    assert "secret-do-not-echo" not in caplog.text
    if provider == "youtube":
        assert requests[0].headers["X-Goog-Api-Key"] == "secret-do-not-echo"
        assert (
            "key" not in requests[0].url.params
            and requests[0].url.params["videoCategoryId"] == "10"
        )
    else:
        assert requests[0].url.params["country"] == "Japan"


REAL_REQUEST = discovery._request
