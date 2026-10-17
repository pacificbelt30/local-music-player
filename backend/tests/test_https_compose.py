"""Verify the optional HTTPS config without starting user's services."""
import json
import os
import shutil
import subprocess
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not shutil.which('docker'), reason='Docker Compose CLI required')


def config(directory, extra_env=None, **values):
    # Use a disposable project so no real .env or user services are touched.
    for name in ("docker-compose.yml", "docker-compose.https.yml"):
        (directory / name).write_text((REPO / name).read_text())
    (directory / ".env").write_text((REPO / ".env.example").read_text())
    env = dict(os.environ)
    for key in ('HTTPS_HOSTNAME', 'HTTPS_PORT', 'HTTPS_URL_PORT', 'HTTPS_BIND_IP', 'HTTPS_OAUTH_REDIRECT_URI', 'YOUTUBE_REDIRECT_URI'):
        env.pop(key, None)
    env.update(values)
    command = ['docker', 'compose', '--project-directory', str(directory),
               '--env-file', str(directory / '.env')]
    if extra_env:
        command.extend(['--env-file', str(extra_env)])
    command.extend(['-f', str(directory / 'docker-compose.yml'),
                    '-f', str(directory / 'docker-compose.https.yml'), 'config', '--format', 'json'])
    return subprocess.run(command, env=env, capture_output=True, text=True)



def test_https_requires_an_explicit_hostname(tmp_path):
    result = config(tmp_path)
    assert result.returncode != 0
    assert 'HTTPS_HOSTNAME' in result.stderr


@pytest.mark.parametrize('port,suffix', [('443', ''), ('8443', ':8443')])
def test_https_redirect_matches_published_url(tmp_path, port, suffix):
    redirect = 'https://music.your-domain.com' + suffix + '/api/v1/youtube/auth/callback'
    result = config(tmp_path, HTTPS_HOSTNAME='music.your-domain.com', HTTPS_PORT=port, HTTPS_URL_PORT=suffix, HTTPS_OAUTH_REDIRECT_URI=redirect)
    assert result.returncode == 0, result.stderr
    spec = json.loads(result.stdout)
    expected = 'https://music.your-domain.com' + suffix + '/api/v1/youtube/auth/callback'
    assert spec['services']['api']['environment']['YOUTUBE_REDIRECT_URI'] == expected
    assert any(str(p['published']) == port for p in spec['services']['https']['ports'])
    assert any(str(p['published']) == '8000' for p in spec['services']['api']['ports'])
    volumes = spec['services']['https']['volumes']
    assert any(v['type'] == 'volume' and v['target'] == '/data' for v in volumes)
    assert any(v['target'] == '/etc/caddy/Caddyfile' and v['read_only'] for v in volumes)


def test_local_https_preserves_existing_oauth_redirect(tmp_path):
    result = config(tmp_path, HTTPS_HOSTNAME='music.home.arpa')
    assert result.returncode == 0, result.stderr
    spec = json.loads(result.stdout)
    assert spec['services']['api']['environment']['YOUTUBE_REDIRECT_URI'] == 'http://localhost:8000/api/v1/youtube/auth/callback'


def test_local_https_respects_explicit_existing_redirect(tmp_path):
    redirect = 'https://music.your-domain.com/api/v1/youtube/auth/callback'
    result = config(tmp_path, HTTPS_HOSTNAME='music.home.arpa', YOUTUBE_REDIRECT_URI=redirect)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['services']['api']['environment']['YOUTUBE_REDIRECT_URI'] == redirect


def test_generated_settings_are_consumed_by_compose(tmp_path):
    import sys
    script = REPO / 'scripts/configure_https.py'
    subprocess.run([sys.executable, str(script), '--hostname', 'music.your-domain.com',
                    '--server-ip', '192.168.1.50', '--port', '8443', '--oauth-mode', 'https',
                    '--output-dir', str(tmp_path)], check=True, capture_output=True)
    result = config(tmp_path, extra_env=tmp_path / 'https.env')
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)['services']
    assert services['api']['environment']['YOUTUBE_REDIRECT_URI'] == 'https://music.your-domain.com:8443/api/v1/youtube/auth/callback'
    assert services['https']['environment']['HTTPS_HOSTNAME'] == 'music.your-domain.com'
    assert any(str(p['published']) == '8443' for p in services['https']['ports'])
