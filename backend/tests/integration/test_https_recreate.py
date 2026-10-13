"""Real local TLS and CA persistence; HTTPS_DOCKER_TESTS=1 opts in."""
import http.client
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import time
import uuid
from urllib.parse import parse_qs, urlparse
import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.skipif(os.environ.get('HTTPS_DOCKER_TESTS') != '1', reason='Opt-in HTTPS Docker integration')


def test_https_verification_oauth_url_and_recreation(tmp_path):
    env = {k:v for k,v in os.environ.items() if k not in ('DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH')}
    name = 'https-test-' + uuid.uuid4().hex[:10]
    host = '192-168-1-50.nip.io'
    spec = yaml.safe_load((REPO / 'docker-compose.https.yml').read_text())['services']['https']
    data = tmp_path / 'ca-data'
    data.mkdir()
    api_data = tmp_path / 'api-data'
    api_data.mkdir()
    api_name, proxy_name = name + '-api', name + '-proxy'
    created = []

    def docker(*args):
        return subprocess.check_output(['docker','--host=unix:///var/run/docker.sock',*args], env=env, text=True, stderr=subprocess.PIPE).strip()

    def start_proxy(port=None):
        if proxy_name not in created: created.append(proxy_name)
        docker('run','-d','--name',proxy_name,'--network',name,
               '-p',f'127.0.0.1:{port or ""}:443', '-e','HTTPS_HOSTNAME='+host,
               '-e','NO_PROXY=api,localhost,127.0.0.1',
               '--mount',f'type=bind,src={REPO / "deploy/https/Caddyfile"},dst=/etc/caddy/Caddyfile,readonly',
               '--mount',f'type=bind,src={data},dst=/data',spec['image'])
        return int(docker('port',proxy_name,'443/tcp').rsplit(':',1)[1])

    def request(port, path, trusted=True, server_name=host):
        context = ssl.create_default_context(cafile=str(tmp_path / 'root.crt')) if trusted else ssl.create_default_context()
        connection = http.client.HTTPSConnection(server_name, port, context=context, timeout=3)
        # Connect solely to our published loopback port; still verify TLS hostname.
        connection._create_connection = lambda *args, **kwargs: socket.create_connection(('127.0.0.1',port), timeout=3)
        try:
            connection.request('GET', path)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def wait(operation):
        end = time.monotonic() + 30
        last = None
        while time.monotonic() < end:
            try:
                result = operation()
                if result: return result
            except (OSError, http.client.HTTPException, subprocess.CalledProcessError) as exc:
                last = exc
            time.sleep(.2)
        pytest.fail(f'HTTPS test did not become ready: {type(last).__name__}')

    docker('network','create',name)
    try:
        created.append(api_name)
        docker('run','-d','--name',api_name,'--network',name,'--network-alias','api',
               '--mount',f'type=bind,src={api_data},dst=/data',
               '-e','DATABASE_URL=sqlite:////data/music.db','-e','DATA_PATH=/data',
               '-e','DOWNLOADS_PATH=/tmp/downloads','-e','PLAYLISTS_PATH=/tmp/playlists',
               '-e','YOUTUBE_CLIENT_ID=test-client','-e','SECRET_TOKEN=',
               '-e','YOUTUBE_REDIRECT_URI=https://'+host+'/api/v1/youtube/auth/callback',
               os.environ.get('HTTPS_APP_TEST_IMAGE','local-music-player:https-test'))
        port = start_proxy()
        def copy_root():
            docker('cp',proxy_name+':/data/caddy/pki/authorities/local/root.crt',str(tmp_path / 'root.crt'))
            return True
        wait(copy_root)
        root = (tmp_path / 'root.crt').read_bytes()
        wait(lambda: request(port,'/api/v1/youtube/auth/url')[0] == 200)
        status, body = request(port,'/')
        assert status == 200 and b'<!DOCTYPE html>' in body
        status, body = request(port,'/api/v1/youtube/auth/url')
        params = parse_qs(urlparse(json.loads(body)['url']).query)
        assert params['redirect_uri'] == ['https://'+host+'/api/v1/youtube/auth/callback']
        assert request(port,'/api/v1/youtube/auth/callback')[0] == 422  # callback route is reachable; code absent
        with pytest.raises(ssl.SSLCertVerificationError): request(port,'/',trusted=False)
        with pytest.raises(ssl.SSLError): request(port,'/',server_name='wrong.example.com')
        docker('rm','-f',proxy_name)
        start_proxy(port)
        wait(lambda: request(port,'/')[0] == 200)  # Same trusted CA after replacing the container.
        docker('cp',proxy_name+':/data/caddy/pki/authorities/local/root.crt',str(tmp_path / 'recreated.crt'))
        assert (tmp_path / 'recreated.crt').read_bytes() == root
    finally:
        for container in reversed(created):
            subprocess.run(['docker','--host=unix:///var/run/docker.sock','rm','-f','-v',container],env=env,capture_output=True)
        subprocess.run(['docker','--host=unix:///var/run/docker.sock','network','rm',name],env=env,capture_output=True)
