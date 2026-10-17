#!/usr/bin/env python3
"""Generate LAN HTTPS and name-resolution settings without modifying the host."""
import argparse
import ipaddress
from pathlib import Path
import re

CALLBACK = '/api/v1/youtube/auth/callback'


def generate(hostname, server_ip, port=443, oauth_mode='localhost'):
    hostname = hostname.lower().rstrip('.')
    if len(hostname) > 253 or '.' not in hostname or any(
        not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
        for label in hostname.split('.')
    ):
        raise ValueError('Specify a DNS hostname such as music.home.arpa, without a URL or port.')
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise ValueError('Specify a hostname, not an IP address.')
    address = ipaddress.ip_address(server_ip)
    if address.is_unspecified or address.is_multicast or address.is_loopback:
        raise ValueError('Specify the server LAN address, not a loopback, multicast or unspecified address.')
    if not 1 <= port <= 65535:
        raise ValueError('HTTPS port must be between 1 and 65535.')
    if oauth_mode not in ('localhost', 'https'):
        raise ValueError('OAuth mode must be localhost or https.')
    if oauth_mode == 'https' and (
        hostname.endswith(('.home.arpa', '.local', '.lan', '.internal', '.localhost', '.test', '.invalid', '.example'))
        or hostname == 'localhost'
    ):
        raise ValueError('Google OAuth HTTPS requires a suitable public-domain hostname; use localhost mode for local-only names.')
    suffix = '' if port == 443 else ':' + str(port)
    base = f'https://{hostname}{suffix}'
    redirect = base + CALLBACK if oauth_mode == 'https' else 'http://localhost:8000' + CALLBACK
    return {
        'https.env': f'HTTPS_HOSTNAME={hostname}\nHTTPS_PORT={port}\nHTTPS_URL_PORT={suffix}\nHTTPS_OAUTH_REDIRECT_URI={redirect}\n',
        'hosts.txt': f'{address} {hostname}\n',
        'dnsmasq.conf': f'host-record={hostname},{address}\n',
        'router-dns.txt': f'Hostname: {hostname}\nRecord type: {"A" if address.version == 4 else "AAAA"}\nAddress: {address}\n',
    }, base, redirect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hostname', required=True)
    parser.add_argument('--server-ip', required=True)
    parser.add_argument('--port', type=int, default=443)
    parser.add_argument('--oauth-mode', choices=['localhost', 'https'], default='localhost',
                        help='localhost preserves the SSH/localhost flow; https requires a Google-acceptable domain')
    parser.add_argument('--output-dir', type=Path, default=Path('https-setup'))
    args = parser.parse_args()
    try:
        files, base, redirect = generate(args.hostname, args.server_ip, args.port, args.oauth_mode)
    except ValueError as exc:
        parser.error(str(exc))
    # Refuse overwrites so an existing setup remains reviewable.
    if any((args.output_dir / name).exists() for name in files):
        parser.error('Output files already exist; choose a new --output-dir.')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (args.output_dir / name).write_text(content, encoding='utf-8')
    print(f'HTTPS URL: {base}')
    print(f'OAuth redirect URI: {redirect}')
    print(f'Settings generated in: {args.output_dir}')
    print('Apply hosts or DNS records on your client/router and install the HTTPS root certificate.')


if __name__ == '__main__':
    main()
