"""Verify the optional HTTPS config without starting user's services."""
import json
import os
import shutil
import subprocess
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not shutil.which('docker'), reason='Docker Compose CLI required')


def config(directory, **values):
    # Use a disposable project so no real .env or user services are touched.
    for name in ("docker-compose.yml", "docker-compose.https.yml"):
        (directory / name).write_text((REPO / name).read_text())
    (directory / ".env").write_text((REPO / ".env.example").read_text())
    env = dict(os.environ)
    for key in ('HTTPS_HOSTNAME', 'HTTPS_PORT', 'HTTPS_URL_PORT', 'HTTPS_BIND_IP'):
        env.pop(key, None)
    env.update(values)
    return subprocess.run(['docker', 'compose', '--project-directory', str(directory),
        '--env-file', str(directory / '.env'), '-f', str(directory / 'docker-compose.yml'),
        '-f', str(directory / 'docker-compose.https.yml'), 'config', '--format', 'json'],
        env=env, capture_output=True, text=True)


def test_https_requires_an_explicit_hostname(tmp_path):
    result = config(tmp_path)
    assert result.returncode != 0
    assert 'HTTPS_HOSTNAME' in result.stderr


@pytest.mark.parametrize('port,suffix', [('443', ''), ('8443', ':8443')])
def test_https_redirect_matches_published_url(tmp_path, port, suffix):
    result = config(tmp_path, HTTPS_HOSTNAME='192-168-1-50.nip.io', HTTPS_PORT=port, HTTPS_URL_PORT=suffix)
    assert result.returncode == 0, result.stderr
    spec = json.loads(result.stdout)
    expected = 'https://192-168-1-50.nip.io' + suffix + '/api/v1/youtube/auth/callback'
    assert spec['services']['api']['environment']['YOUTUBE_REDIRECT_URI'] == expected
    assert any(str(p['published']) == port for p in spec['services']['https']['ports'])
    assert any(str(p['published']) == '8000' for p in spec['services']['api']['ports'])
    volumes = spec['services']['https']['volumes']
    assert any(v['type'] == 'volume' and v['target'] == '/data' for v in volumes)
    assert any(v['target'] == '/etc/caddy/Caddyfile' and v['read_only'] for v in volumes)
