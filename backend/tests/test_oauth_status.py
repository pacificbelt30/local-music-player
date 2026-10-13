from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import httpx
import pytest
from app.models import YouTubeOAuthToken
from app.services import youtube_api_service as oauth


def token(db, **values):
    row = YouTubeOAuthToken(access_token='private-access', refresh_token='private-refresh',
                            token_expiry=datetime.now(timezone.utc) - timedelta(seconds=1), **values)
    db.add(row)
    db.commit()
    return row


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    monkeypatch.setattr(oauth.settings, 'youtube_client_id', 'client')
    monkeypatch.setattr(oauth.settings, 'youtube_client_secret', 'secret')
    monkeypatch.setattr(oauth.settings, 'youtube_oauth_publish_status', 'unknown')


def test_status_keeps_unknown_expiry_and_does_not_contact_google(client, db):
    token(db)
    with patch.object(oauth, 'refresh_access_token') as refresh:
        data = client.get('/api/v1/youtube/auth/status').json()
    refresh.assert_not_called()
    assert data['refresh_status'] == 'available'
    assert data['access_token_expired'] is True
    assert data['refresh_token_expiry'] is None
    assert data['authorized_at'] is None
    assert 'private-' not in str(data)


def test_explicit_check_records_success(client, db):
    row = token(db, refresh_error='invalid_grant')
    with patch.object(oauth, 'refresh_access_token', return_value={'access_token': 'new', 'expires_in': 3600}):
        data = client.post('/api/v1/youtube/auth/check').json()
    db.refresh(row)
    assert data['refresh_status'] == 'available'
    assert data['last_refresh_at']
    assert data['access_token_expired'] is False
    assert row.refresh_error is None


@pytest.mark.parametrize('code, expected', [('invalid_grant', 'reauth_required'), ('invalid_client', 'configuration_error'), ('server_error', 'temporary_error')])
def test_refresh_errors_are_safe_and_persisted(client, db, code, expected):
    token(db)
    response = httpx.Response(400, json={'error': code, 'error_description': 'private-refresh'}, request=httpx.Request('POST', oauth.GOOGLE_TOKEN_URL))
    with patch.object(oauth, 'refresh_access_token', side_effect=httpx.HTTPStatusError('unsafe', request=response.request, response=response)):
        data = client.post('/api/v1/youtube/auth/check').json()
    assert data['refresh_status'] == expected
    assert 'private-' not in str(data)
    assert client.get('/api/v1/youtube/auth/status').json()['refresh_status'] == expected


def test_network_failure_is_retryable(client, db):
    token(db)
    with patch.object(oauth, 'refresh_access_token', side_effect=httpx.ConnectError('offline')):
        data = client.post('/api/v1/youtube/auth/check').json()
    assert data['refresh_status'] == 'temporary_error'
    with patch.object(oauth, 'refresh_access_token', return_value={'access_token': 'new'}):
        data = client.post('/api/v1/youtube/auth/check').json()
    assert data['refresh_status'] == 'available'


def test_missing_refresh_token_does_not_call_google(client, db):
    row = token(db)
    row.refresh_token = ''
    db.commit()
    with patch.object(oauth, 'refresh_access_token') as refresh:
        data = client.post('/api/v1/youtube/auth/check').json()
    refresh.assert_not_called()
    assert data['refresh_status'] == 'reauth_required'


def test_testing_expiry_is_an_estimate_not_renewed_by_refresh(client, db, monkeypatch):
    monkeypatch.setattr(oauth.settings, 'youtube_oauth_publish_status', 'testing')
    authorized = datetime.now(timezone.utc) - timedelta(days=6)
    token(db, authorized_at=authorized)
    before = client.get('/api/v1/youtube/auth/status').json()
    with patch.object(oauth, 'refresh_access_token', return_value={'access_token': 'new'}):
        after = client.post('/api/v1/youtube/auth/check').json()
    assert after['refresh_token_expiry'] == before['refresh_token_expiry']
    assert after['refresh_expiry_estimated'] is True


def test_provider_expiry_overrides_testing_estimate(client, db, monkeypatch):
    monkeypatch.setattr(oauth.settings, 'youtube_oauth_publish_status', 'testing')
    token(db, authorized_at=datetime.now(timezone.utc))
    with patch.object(oauth, 'refresh_access_token', return_value={'access_token': 'new', 'refresh_token_expires_in': 100}):
        data = client.post('/api/v1/youtube/auth/check').json()
    assert data['refresh_token_expiry']
    assert data['refresh_expiry_estimated'] is False


def test_reauthorization_starts_new_lifetime_only_when_refresh_token_issued(client, db):
    row = token(db, authorized_at=datetime.now(timezone.utc) - timedelta(days=6), refresh_error='invalid_grant')
    before = row.authorized_at
    with patch.object(oauth, 'exchange_code', return_value={'access_token': 'new'}):
        client.get('/api/v1/youtube/auth/callback?code=x', follow_redirects=False)
    db.refresh(row)
    assert row.authorized_at == before
    assert row.refresh_error == 'invalid_grant'
    with patch.object(oauth, 'exchange_code', return_value={'access_token': 'new', 'refresh_token': 'new-refresh', 'refresh_token_expires_in': 500}):
        client.get('/api/v1/youtube/auth/callback?code=x', follow_redirects=False)
    db.refresh(row)
    assert row.authorized_at > before
    assert row.refresh_token_expiry
    assert row.refresh_error is None


def test_automatic_refresh_records_diagnostics(db):
    row = token(db)
    with patch.object(oauth, 'refresh_access_token', return_value={'access_token': 'new'}):
        assert oauth.get_fresh_access_token(db) == 'new'
    assert row.last_refresh_at


def test_expiry_notification_skips_automatically_renewable_access_token(db):
    from app.tasks.scheduler import periodic_oauth_expiry_check
    row = token(db)
    row.token_expiry = datetime.now(timezone.utc) + timedelta(minutes=20)
    db.commit()
    with patch('app.tasks.scheduler.SessionLocal', return_value=db), patch('app.services.notification.notify') as notify:
        periodic_oauth_expiry_check.apply()
    notify.assert_not_called()


def test_unconfigured_check_never_contacts_google(client, db, monkeypatch):
    token(db)
    monkeypatch.setattr(oauth.settings, 'youtube_client_secret', '')
    with patch.object(oauth, 'refresh_access_token') as refresh:
        data = client.post('/api/v1/youtube/auth/check').json()
    refresh.assert_not_called()
    assert data['refresh_status'] == 'configuration_error'


def test_testing_expiry_is_not_proof_of_actual_revocation(client, db, monkeypatch):
    monkeypatch.setattr(oauth.settings, 'youtube_oauth_publish_status', 'testing')
    token(db, authorized_at=datetime.now(timezone.utc) - timedelta(days=8))
    data = client.get('/api/v1/youtube/auth/status').json()
    assert data['refresh_status'] == 'check_required'
    assert data['refresh_expiry_estimated'] is True


def test_pasted_refresh_token_does_not_invent_issuance_date(client, db, monkeypatch):
    monkeypatch.setattr(oauth.settings, 'youtube_oauth_publish_status', 'testing')
    client.post('/api/v1/youtube/auth/token', json={'access_token':'pasted', 'refresh_token':'pasted-refresh'})
    data = client.get('/api/v1/youtube/auth/status').json()
    assert data['authorized_at'] is None
    assert data['refresh_token_expiry'] is None


def test_successful_check_after_estimated_expiry_reports_available(client, db, monkeypatch):
    monkeypatch.setattr(oauth.settings, 'youtube_oauth_publish_status', 'testing')
    token(db, authorized_at=datetime.now(timezone.utc) - timedelta(days=8))
    with patch.object(oauth, 'refresh_access_token', return_value={'access_token':'new'}):
        data = client.post('/api/v1/youtube/auth/check').json()
    assert data['refresh_status'] == 'available'
    assert data['refresh_expiry_estimated'] is True


def test_migration_preserves_existing_tokens_and_unknown_lifetimes(tmp_path, monkeypatch):
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    root = Path(__file__).resolve().parents[1]
    url = 'sqlite:///' + str(tmp_path / 'legacy.db')
    monkeypatch.setattr(oauth.settings, 'database_url', url)
    cfg = Config(str(root / 'alembic.ini'))
    cfg.set_main_option('script_location', str(root / 'migrations'))
    command.upgrade(cfg, 'f6a7b8c9d0e1')
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO youtube_oauth_tokens(access_token,refresh_token) VALUES ('legacy-access','legacy-refresh')"))
    command.upgrade(cfg, 'head')
    with engine.connect() as connection:
        row = connection.execute(text('SELECT access_token,refresh_token,authorized_at,refresh_token_expiry,last_refresh_at,refresh_error FROM youtube_oauth_tokens')).one()
        assert tuple(row) == ('legacy-access','legacy-refresh',None,None,None,None)
    command.downgrade(cfg, 'f6a7b8c9d0e1')
    with engine.connect() as connection:
        assert connection.execute(text('SELECT refresh_token FROM youtube_oauth_tokens')).scalar() == 'legacy-refresh'
    engine.dispose()
