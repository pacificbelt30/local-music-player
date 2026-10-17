"""Opt-in real Docker peers: SYNCTHING_DOCKER_TESTS=1 pytest tests/integration/.

Only test-owned containers/networks and temporary bind directories are touched.
"""
import asyncio
import json
import os
import shlex
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path

import pytest
import yaml

from app.models import AppSetting
from app.services import syncthing_service

pytestmark = pytest.mark.skipif(os.environ.get("SYNCTHING_DOCKER_TESTS") != "1", reason="Opt-in Docker integration test")
REPO = Path(__file__).resolve().parents[3]


class ContainerFile:
    """Access fixtures as the service UID, independent of the host runner UID."""
    def __init__(self, peers, node, name):
        self.peers = peers
        self.container = peers.name + "-" + node
        self.path = "/var/syncthing/Sync/" + name

    def run(self, *args):
        return self.peers.docker("exec", "--user", "1000:1000", self.container, *args)

    def write_text(self, content):
        self.run("sh", "-c", 'printf %s "$1" > "$2"', "write-fixture", content, self.path)

    def read_text(self):
        return self.run("cat", self.path)

    def exists(self):
        try:
            self.run("test", "-e", self.path)
            return True
        except subprocess.CalledProcessError:
            return False

    def is_dir(self):
        self.run("test", "-d", self.path)
        return True

    def unlink(self):
        self.run("rm", self.path)


class Peers:
    def __init__(self, directory, legacy=False):
        self.directory = directory
        self.legacy = legacy
        self.name = "syncthing-test-" + uuid.uuid4().hex[:10]
        self.key = uuid.uuid4().hex
        self.names = []
        self.spec = yaml.safe_load((REPO / "docker-compose.yml").read_text())["services"]["syncthing"]
        self.env = {k: v for k, v in os.environ.items() if k not in
                    ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH")}
        self.docker("network", "create", self.name)

    def docker(self, *args):
        return subprocess.check_output(["docker", "--host=unix:///var/run/docker.sock", *args],
                                       env=self.env, text=True, stderr=subprocess.PIPE).strip()

    def mounts(self, node):
        args = []
        for mapping in self.spec["volumes"]:
            source, target = mapping.split(":")
            if self.legacy and target == "/var/syncthing":
                continue
            path = self.directory / node / Path(source).name
            if not path.exists():
                path.mkdir(parents=True)
                path.chmod(0o777)
            args.extend(["--mount", f"type=bind,src={path},dst={target}"])
        return args

    def start(self, node, port=None):
        name = self.name + "-" + node
        mounts = self.mounts(node)
        self.docker("run", "--rm", *mounts, "--entrypoint", "sh", self.spec["image"],
                    "-c", "chown -R 1000:1000 /var/syncthing")
        health = shlex.join(self.spec["healthcheck"]["test"][1:])
        if name not in self.names:
            self.names.append(name)
        self.docker("run", "-d", "--name", name, "--network", self.name, "--network-alias", node,
                    "-p", f"127.0.0.1:{port or ''}:8384", "-e", "PUID=1000", "-e", "PGID=1000",
                    "-e", "STGUIADDRESS=0.0.0.0:8384", "-e", "STGUIAPIKEY=" + self.key,
                    "--health-cmd", health, "--health-interval", "1s", "--health-retries", "30",
                    *mounts, self.spec["image"])
        port = int(self.docker("port", name, "8384/tcp").rsplit(":", 1)[1])
        wait(lambda: self.docker("inspect", "--format", "{{.State.Health.Status}}", name) == "healthy")
        identity = self.api(port, "system/status")["myID"]
        return port, identity

    def api(self, port, path, body=None, method=None):
        request = urllib.request.Request(f"http://127.0.0.1:{port}/rest/{path}",
                    data=json.dumps(body).encode() if body is not None else None,
                    headers={"X-API-Key": self.key, "Content-Type": "application/json"}, method=method)
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=5) as response:
            content = response.read()
            return json.loads(content) if content else None

    def app_request(self, port, path):
        request = urllib.request.Request(f"http://127.0.0.1:{port}/api/v1/syncthing/{path}")
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=20) as response:
            return json.loads(response.read())

    def start_app(self, image):
        name = self.name + "-api"
        self.names.append(name)
        data = self.directory / "app-data"
        data.mkdir()
        self.docker("run", "-d", "--name", name, "--network", self.name, "-p", "127.0.0.1::8000",
                    "--mount", f"type=bind,src={data},dst=/data", "-e", "DATABASE_URL=sqlite:////data/music.db",
                    "-e", "DATA_PATH=/data", "-e", "DOWNLOADS_PATH=/tmp/downloads", "-e", "PLAYLISTS_PATH=/tmp/playlists",
                    "-e", "SYNCTHING_URL=http://a:8384", "-e", "SYNCTHING_API_KEY=" + self.key,
                    "-e", "SECRET_TOKEN=", image)
        port = int(self.docker("port", name, "8000/tcp").rsplit(":", 1)[1])
        wait(lambda: self.app_request(port, "config")["api_key_set"])
        return port

    def pair(self, pa, ida, pb, idb):
        for port, own, peer, host in ((pa, ida, idb, "b"), (pb, idb, ida, "a")):
            self.api(port, "config/options", {
                "listenAddresses": ["tcp://0.0.0.0:22000"], "globalAnnounceEnabled": False,
                "localAnnounceEnabled": False, "relaysEnabled": False, "natEnabled": False,
                "reconnectionIntervalS": 1,
            }, "PATCH")
            self.api(port, "config/devices", {"deviceID": peer, "name": "Peer", "addresses": [f"tcp://{host}:22000"]}, "POST")
            self.api(port, "config/folders", {"id": "music", "label": "Music", "path": "/var/syncthing/Sync",
                     "type": "sendreceive", "rescanIntervalS": 1, "fsWatcherEnabled": False,
                     "devices": [{"deviceID": own}, {"deviceID": peer}]}, "POST")
        wait(lambda: self.connected(pa, idb))
        wait(lambda: self.api(pa, "db/status?folder=music")["state"] == "idle")

    def connected(self, port, peer):
        return self.api(port, "system/connections")["connections"].get(peer, {}).get("connected")

    def file(self, node, name):
        return ContainerFile(self, node, name)

    def remove(self, node):
        self.docker("rm", "-f", "-v", self.name + "-" + node)

    def change_ip(self, node):
        name = self.name + "-" + node
        ip = json.loads(self.docker("inspect", name))[0]["NetworkSettings"]["Networks"][self.name]["IPAddress"]
        self.remove(node)
        blocker = self.name + "-old-ip"
        self.names.append(blocker)
        self.docker("run", "-d", "--name", blocker, "--network", self.name,
                    "--entrypoint", "sh", self.spec["image"], "-c", "sleep 120")
        return ip

    def cleanup(self):
        for name in self.names:
            try:
                self.docker("rm", "-f", "-v", name)
            except subprocess.CalledProcessError:
                pass
        # Restore ownership of test-only bind mounts for non-root CI cleanup.
        self.docker("run", "--rm", "--entrypoint", "sh", "--mount",
                    f"type=bind,src={self.directory},dst=/test-data", self.spec["image"],
                    "-c", f"chown -R {os.getuid()}:{os.getgid()} /test-data")
        self.docker("network", "rm", self.name)


def wait(predicate, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except (OSError, KeyError, subprocess.CalledProcessError):
            pass
        time.sleep(0.2)
    raise AssertionError("Syncthing did not reach the expected state within the deadline")


@pytest.fixture
def peers(tmp_path):
    peers = Peers(tmp_path)
    try:
        yield peers
    finally:
        peers.cleanup()


def test_recreation_with_changed_ip_preserves_identity_pairing_and_bidirectional_sync(peers, db):
    pa, ida = peers.start("a")
    pb, idb = peers.start("b")
    peers.pair(pa, ida, pb, idb)
    peers.file("a", "before.txt").write_text("before")
    peers.api(pa, "db/scan?folder=music", method="POST")
    wait(lambda: peers.file("b", "before.txt").exists())
    db.add_all([AppSetting(key="syncthing_url", value=f"http://127.0.0.1:{pa}"),
                AppSetting(key="syncthing_api_key", value=peers.key)])
    db.commit()
    old_ip = peers.change_ip("a")
    assert not asyncio.run(syncthing_service.get_syncthing_status(db))["available"]
    pa, new_id = peers.start("a", port=pa)
    assert new_id == ida
    new_ip = json.loads(peers.docker("inspect", peers.name + "-a"))[0]["NetworkSettings"]["Networks"][peers.name]["IPAddress"]
    assert new_ip != old_ip
    wait(lambda: peers.connected(pa, idb))
    assert peers.file("a", ".stfolder").is_dir()
    assert peers.file("a", "before.txt").read_text() == "before"
    assert peers.api(pa, "db/status?folder=music")["error"] == ""
    peers.file("a", "after.txt").write_text("after")
    peers.api(pa, "db/scan?folder=music", method="POST")
    wait(lambda: peers.file("b", "after.txt").exists())
    peers.file("b", "return.txt").write_text("return")
    peers.api(pb, "db/scan?folder=music", method="POST")
    wait(lambda: peers.file("a", "return.txt").exists())
    peers.file("a", "before.txt").unlink()
    peers.api(pa, "db/scan?folder=music", method="POST")
    wait(lambda: not peers.file("b", "before.txt").exists())
    wait(lambda: asyncio.run(syncthing_service.get_syncthing_status(db)).get("state") == "synced")
    devices = asyncio.run(syncthing_service.list_devices(db))
    assert len(devices) == 1 and devices[0]["connected"]


def test_old_layout_reproduces_missing_folder_after_container_recreation(tmp_path, db):
    peers = Peers(tmp_path, legacy=True)
    try:
        pa, ida = peers.start("a")
        pb, idb = peers.start("b")
        peers.pair(pa, ida, pb, idb)
        peers.docker("exec", peers.name + "-a", "sh", "-c", "printf before > /var/syncthing/Sync/before.txt")
        peers.api(pa, "db/scan?folder=music", method="POST")
        peers.remove("a")
        pa, new_id = peers.start("a", port=pa)
        assert new_id == ida
        wait(lambda: peers.api(pa, "db/status?folder=music").get("error") == "folder path missing")
        db.add_all([AppSetting(key="syncthing_url", value=f"http://127.0.0.1:{pa}"),
                    AppSetting(key="syncthing_api_key", value=peers.key)])
        db.commit()
        assert asyncio.run(syncthing_service.get_syncthing_status(db))["state"] == "error"
    finally:
        peers.cleanup()


def test_api_container_recovers_via_service_dns_without_changing_configuration(peers):
    image = os.environ.get("SYNCTHING_APP_TEST_IMAGE")
    if not image:
        pytest.skip("Set SYNCTHING_APP_TEST_IMAGE to a freshly built application image")
    pa, ida = peers.start("a")
    pb, idb = peers.start("b")
    peers.pair(pa, ida, pb, idb)
    app_port = peers.start_app(image)
    wait(lambda: peers.app_request(app_port, "status").get("state") == "synced")
    peers.change_ip("a")
    assert peers.app_request(app_port, "status")["available"] is False
    pa, new_id = peers.start("a", port=pa)
    assert new_id == ida
    wait(lambda: peers.connected(pa, idb))
    peers.file("a", "from-recreated.txt").write_text("from recreated server")
    peers.api(pa, "db/scan?folder=music", method="POST")
    wait(lambda: peers.file("b", "from-recreated.txt").exists())
    wait(lambda: peers.app_request(app_port, "status").get("state") == "synced")
    assert peers.app_request(app_port, "config")["url"] == "http://a:8384"
