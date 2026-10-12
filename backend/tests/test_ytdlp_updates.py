import json
import io
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services import ytdlp_process, ytdlp_updates as updates


@pytest.fixture
def candidate(monkeypatch):
    updates.configure(updates.UpdateConfig(
        video_url="https://www.youtube.com/watch?v=reference",
        playlist_url="https://www.youtube.com/playlist?list=reference",
    ))
    monkeypatch.setattr(updates, "latest_version", lambda: "2099.1.1")
    monkeypatch.setattr(updates, "download_options", lambda: {})
    directory = updates.root() / "installations" / "candidate"
    directory.mkdir(parents=True)
    installation = {"version": "2099.1.1", "path": str(directory)}
    monkeypatch.setattr(updates, "install", lambda version: installation)
    return installation


def test_promotion_is_atomic_and_existing_installation_survives(monkeypatch, candidate):
    previous = updates.active_installation()
    selected = []

    def probe(installation, config, options):
        selected.append(installation)
        # Downloads started while tests run must still select the old version.
        assert updates.active_installation() == previous
        return {"passed": True, "version": installation["version"], "checks": ["ok"]}

    monkeypatch.setattr(updates, "run_probe", probe)
    state = updates.check(force=True)
    assert state["status"] == "updated"
    assert updates.active_installation() == candidate
    assert state["previous"] == previous
    assert selected == [previous, candidate]
    assert Path(candidate["path"]).is_dir()
    rollback = updates.rollback()
    assert rollback["active"] == previous
    assert rollback["config"]["enabled"] is False
    # In-flight requests using the candidate must retain their files after rollback.
    assert Path(candidate["path"]).is_dir()


@pytest.mark.parametrize("baseline_passed,expected", [(True, "rejected"), (False, "inconclusive")])
def test_failed_candidate_preserves_current(monkeypatch, candidate, baseline_passed, expected):
    current = updates.active_installation()
    def probe(installation, config, options):
        return {"passed": baseline_passed if installation == current else False,
                "version": installation["version"], "error": "network or API changed"}
    monkeypatch.setattr(updates, "run_probe", probe)
    state = updates.check(force=True)
    assert state["status"] == expected
    assert updates.active_installation() == current
    assert not Path(candidate["path"]).exists()


def test_candidate_can_repair_broken_current(monkeypatch, candidate):
    monkeypatch.setattr(updates, "run_probe", lambda installation, config, options: {
        "passed": installation == candidate, "version": installation["version"], "error": "old extractor failed",
    })
    assert updates.check(force=True)["status"] == "updated"


def test_install_failure_preserves_current(monkeypatch, candidate):
    current = updates.active_installation()
    def fail(version):
        raise RuntimeError("disk full")
    monkeypatch.setattr(updates, "install", fail)
    assert updates.check(force=True)["status"] == "failed"
    assert updates.active_installation() == current


def test_no_test_urls_never_installs(monkeypatch):
    monkeypatch.setattr(updates, "latest_version", lambda: "2099.1.1")
    with patch.object(updates, "install") as install:
        assert updates.check(force=True)["status"] == "needs_configuration"
    install.assert_not_called()


def test_periodic_check_respects_disabled_and_interval(monkeypatch):
    updates.configure(updates.UpdateConfig(enabled=False))
    with patch.object(updates, "latest_version") as latest:
        updates.check()
        latest.assert_not_called()
    updates.configure(updates.UpdateConfig())
    state = updates.read_state()
    state["last_checked_at"] = datetime.now(timezone.utc).isoformat()
    updates.save_state(state)
    with patch.object(updates, "latest_version") as latest:
        updates.check()
        latest.assert_not_called()


def test_same_release_with_zero_padding_does_not_reinstall(monkeypatch):
    state = updates.read_state()
    monkeypatch.setattr(updates, "latest_version", lambda: ".".join(str(int(v)) for v in state["active"]["version"].split(".")))
    with patch.object(updates, "install") as install:
        assert updates.check(force=True)["status"] == "up_to_date"
        install.assert_not_called()


def test_latest_version_reads_large_pypi_release_history(monkeypatch):
    payload = json.dumps({"info": {"version": "2026.8.19"}, "releases": "x" * (1024 * 1024)}).encode()
    monkeypatch.setattr(updates.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(payload))
    assert updates.latest_version() == "2026.8.19"


@pytest.mark.parametrize("version", ["2099.1.1;command", "../../escape", "2026.8.19rc1"])
def test_install_rejects_non_stable_versions(version):
    with pytest.raises(ValueError):
        updates.install(version)


def test_duplicate_check_and_rollback_cannot_mutate_during_update():
    with updates.mutation_lock():
        assert updates.check(force=True)["busy"]
        with pytest.raises(updates.UpdateBusy):
            updates.rollback()
        with pytest.raises(updates.UpdateBusy):
            updates.configure(updates.UpdateConfig())
        assert updates.status()["busy"]


def test_interrupted_worker_is_reported_and_can_recover():
    state = updates.read_state()
    state["status"] = "testing"
    updates.save_state(state)
    result = updates.status()
    assert result["status"] == "interrupted"
    assert not result["busy"]
    assert result["active"] == state["active"]


def test_probe_rejects_wrong_loaded_version(monkeypatch):
    monkeypatch.setattr(ytdlp_process, "call", lambda *args, **kwargs: {"version": "2000.1.1", "checks": []})
    result = updates.run_probe(updates.bundled(), {}, {})
    assert not result["passed"]
    assert "differs" in result["error"]


def test_api_status_configuration_check_and_rollback(client):
    response = client.get("/api/v1/ytdlp")
    assert response.status_code == 200
    assert response.json()["config"]["interval_minutes"] == 1440
    assert client.patch("/api/v1/ytdlp/config", json={"interval_minutes": 1}).status_code == 422
    assert client.patch("/api/v1/ytdlp/config", json={"video_url": "https://example.com/video"}).status_code == 422
    assert client.patch("/api/v1/ytdlp/config", json={"enabled": False}).status_code == 200
    with patch("app.tasks.ytdlp_update.check_ytdlp_update.apply_async") as enqueue:
        enqueue.return_value.id = "job-id"
        assert client.post("/api/v1/ytdlp/check").json()["task_id"] == "job-id"
        enqueue.assert_called_once_with(kwargs={"force": True}, expires=300)
    assert client.post("/api/v1/ytdlp/rollback").status_code == 409
    with updates.mutation_lock():
        assert client.post("/api/v1/ytdlp/check").status_code == 409
        assert client.patch("/api/v1/ytdlp/config", json={}).status_code == 409


def test_update_routes_share_existing_auth(client, monkeypatch):
    monkeypatch.setattr("app.config.settings.secret_token", "test-secret")
    assert client.post("/api/v1/ytdlp/check").status_code == 401
    assert client.get("/api/v1/ytdlp", headers={"Authorization": "Bearer test-secret"}).status_code == 200


def test_download_dispatch_preserves_options_and_progress(monkeypatch, tmp_path):
    from app.services import ytdlp_service
    monkeypatch.delenv("YTDLP_CHILD")
    progress = lambda event: None
    with patch.object(ytdlp_process, "call", return_value={"file_format": "mp3"}) as call:
        ytdlp_service.download_track("id", "mp3", "192", 10, base_path=tmp_path, progress_hook=progress)
    args, kwargs = call.call_args
    assert args[0] == "download_track"
    assert args[1]["base_path"] == tmp_path
    assert args[1]["gain_percent"] == 10
    assert "call" not in args[1] and "progress_hook" not in args[1]
    assert kwargs["progress_hook"] is progress


def fixture_installation(tmp_path, source):
    # Substitute only the runner protocol peer, using a real OS process.
    directory = tmp_path / "packages" / "app" / "services"
    directory.mkdir(parents=True)
    (directory.parent / "__init__.py").touch()
    (directory / "__init__.py").touch()
    (directory / "ytdlp_runner.py").write_text(source)
    return {"version": "2099.1.1", "path": str(tmp_path / "packages")}


def test_real_process_uses_selected_installation_and_streams_progress(tmp_path):
    installation = fixture_installation(tmp_path, '''
import json, sys
request = json.loads(sys.stdin.readline())
print(json.dumps({"type":"progress", "data":{"status":"downloading", "downloaded_bytes":10}}), flush=True)
print(json.dumps({"type":"result", "data":{"selected":"candidate", "operation":request["operation"]}}), flush=True)
''')
    events = []
    result = ytdlp_process.call("resolve_url", {}, installation=installation, progress_hook=events.append, timeout=10)
    assert result == {"selected": "candidate", "operation": "resolve_url"}
    assert events[0]["downloaded_bytes"] == 10


def test_real_process_timeout_kills_descendants(tmp_path):
    pidfile = tmp_path / "child-pid"
    installation = fixture_installation(tmp_path, f'''
import json, sys, subprocess, time
json.loads(sys.stdin.readline())
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
open({str(pidfile)!r}, "w").write(str(child.pid))
time.sleep(60)
''')
    with pytest.raises(TimeoutError):
        ytdlp_process.call("probe", {}, installation=installation, timeout=1)
    if pidfile.exists():
        pid = int(pidfile.read_text())
        stat = Path(f"/proc/{pid}/stat")
        import time
        deadline = time.monotonic() + 2
        while stat.exists() and stat.read_text().split()[2] != "Z" and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not stat.exists() or stat.read_text().split()[2] == "Z"


def test_real_process_request_keeps_version_while_active_pointer_changes(tmp_path):
    entered = tmp_path / "entered"
    release = tmp_path / "release"
    installation = fixture_installation(tmp_path, f'''
import json, sys, time
json.loads(sys.stdin.readline())
from pathlib import Path
Path({str(entered)!r}).touch()
while not Path({str(release)!r}).exists(): time.sleep(0.01)
print(json.dumps({{"type":"result", "data":"original"}}), flush=True)
''')
    state = updates.read_state()
    state["active"] = installation
    updates.save_state(state)
    result = []
    thread = threading.Thread(target=lambda: result.append(ytdlp_process.call("probe", {}, timeout=10)))
    thread.start()
    import time
    deadline = time.monotonic() + 5
    while not entered.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    try:
        assert entered.exists()
        state["active"] = updates.bundled()
        updates.save_state(state)
        assert updates.active_installation() == updates.bundled()
    finally:
        release.touch()
        thread.join(timeout=10)
    assert result == ["original"]


def test_actual_ytdlp_and_ffmpeg_in_child_process():
    result = ytdlp_process.call("local_probe", {}, installation=updates.bundled(), timeout=120)
    assert len(result["checks"]) == 7
    assert updates.version_key(result["version"]) == updates.version_key(updates.bundled()["version"])


def test_periodic_task_routes_to_dedicated_worker():
    from app.tasks.celery_app import celery_app
    assert celery_app.conf.task_routes["app.tasks.ytdlp_update.*"]["queue"] == "updates"
    assert celery_app.conf.beat_schedule["check-ytdlp-update"]["task"] == "app.tasks.ytdlp_update.check"
