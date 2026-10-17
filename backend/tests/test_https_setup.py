"""The setup helper generates files, never applies privileged host/DNS changes."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/configure_https.py'
spec = importlib.util.spec_from_file_location('https_setup', SCRIPT)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def test_local_setup_generates_hosts_dns_and_preserves_localhost_oauth():
    files, base, redirect = setup.generate('Music.Home.Arpa.', '192.168.1.50')
    assert base == 'https://music.home.arpa'
    assert redirect == 'http://localhost:8000/api/v1/youtube/auth/callback'
    assert files['hosts.txt'] == '192.168.1.50 music.home.arpa\n'
    assert files['dnsmasq.conf'] == 'host-record=music.home.arpa,192.168.1.50\n'
    assert 'Record type: A\n' in files['router-dns.txt']


def test_custom_port_keeps_https_and_callback_consistent():
    files, base, redirect = setup.generate('music.your-domain.com', '192.168.1.50', 8443, 'https')
    assert base == 'https://music.your-domain.com:8443'
    assert redirect == base + setup.CALLBACK
    assert 'HTTPS_URL_PORT=:8443\n' in files['https.env']
    assert 'HTTPS_PORT=8443\n' in files['https.env']


def test_ipv6_generates_aaaa_and_valid_hosts_record():
    files, _, _ = setup.generate('music.home.arpa', 'fd12:3456::50')
    assert 'Record type: AAAA\n' in files['router-dns.txt']
    assert files['hosts.txt'].startswith('fd12:3456::50 ')


@pytest.mark.parametrize('hostname', ['localhost', 'https://music.home.arpa', 'music.home.arpa:443', '192.168.1.50', 'bad\nNAME=evil.com', '-bad.example.com', 'music..example.com'])
def test_invalid_names_cannot_inject_settings(hostname):
    with pytest.raises(ValueError): setup.generate(hostname, '192.168.1.50')


@pytest.mark.parametrize('hostname', ['music.home.arpa', 'music.local', 'music.lan', 'music.test'])
def test_local_only_names_cannot_be_selected_as_google_https_callback(hostname):
    with pytest.raises(ValueError): setup.generate(hostname, '192.168.1.50', oauth_mode='https')


@pytest.mark.parametrize('address', ['not-an-ip', '127.0.0.1', '0.0.0.0', '224.0.0.1'])
def test_invalid_server_addresses(address):
    with pytest.raises(ValueError): setup.generate('music.home.arpa', address)


def test_cli_does_not_overwrite_existing_settings(tmp_path):
    args = [sys.executable, str(SCRIPT), '--hostname', 'music.home.arpa', '--server-ip', '192.168.1.50', '--output-dir', str(tmp_path)]
    first = subprocess.run(args, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    initial = {p.name:p.read_bytes() for p in tmp_path.iterdir()}
    assert set(initial) == {'https.env', 'hosts.txt', 'dnsmasq.conf', 'router-dns.txt'}
    second = subprocess.run(args, capture_output=True, text=True)
    assert second.returncode != 0
    assert 'already exist' in second.stderr
    assert initial == {p.name:p.read_bytes() for p in tmp_path.iterdir()}


@pytest.mark.parametrize('port', [0, 65536])
def test_invalid_ports(port):
    with pytest.raises(ValueError): setup.generate('music.home.arpa', '192.168.1.50', port)
