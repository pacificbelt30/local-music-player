"""Saved download settings apply to new jobs; shared playlists need no account."""
from unittest.mock import patch

import pytest

from app.models import YoutubePlaylistSync


def test_defaults_remain_compatible(client):
    settings = client.get('/api/v1/settings').json()
    assert settings['default_audio_format'] == 'mp3'
    assert settings['default_audio_quality'] == '192'
    assert settings['account_playlist_method'] == 'url'


def test_preferences_persist_and_do_not_change_existing_syncs(client, db):
    sync = YoutubePlaylistSync(playlist_id='existing', playlist_name='Existing', audio_format='mp3', audio_quality='192')
    db.add(sync)
    db.commit()
    payload = {'default_audio_format': 'm4a', 'default_audio_quality': '320', 'account_playlist_method': 'api'}
    response = client.patch('/api/v1/settings', json=payload)
    assert response.status_code == 200
    saved = client.get('/api/v1/settings').json()
    assert {key:saved[key] for key in payload} == payload
    db.refresh(sync)
    assert sync.audio_format == 'mp3' and sync.audio_quality == '192'


@pytest.mark.parametrize('payload', [{'default_audio_format':'exe'}, {'default_audio_quality':'999'}, {'account_playlist_method':'other'}])
def test_invalid_preferences_are_rejected_atomically(client, payload):
    response = client.patch('/api/v1/settings', json={**payload, 'url_sync_interval_minutes':15})
    assert response.status_code == 422
    assert client.get('/api/v1/settings').json()['url_sync_interval_minutes'] == 60


def test_new_download_uses_saved_media_defaults_and_honors_explicit_overrides(client):
    client.patch('/api/v1/settings', json={'default_audio_format':'m4a', 'default_audio_quality':'320'})
    with patch('app.api.urls.resolve_url_task.apply_async'):
        inherited = client.post('/api/v1/urls', json={'url':'https://youtu.be/jNQXAC9IVRw'})
        explicit = client.post('/api/v1/urls', json={'url':'https://youtu.be/aqz-KE-bpKQ','audio_format':'mp3','audio_quality':'192'})
    assert inherited.status_code == 201
    assert inherited.json()['audio_format'] == 'm4a' and inherited.json()['audio_quality'] == '320'
    assert explicit.json()['audio_format'] == 'mp3' and explicit.json()['audio_quality'] == '192'


@pytest.mark.parametrize('playlist_id', ['PLsomeone-public', 'PLsomeone-unlisted'])
def test_shared_playlist_without_oauth_is_synced_by_url_with_saved_defaults(client, playlist_id):
    client.patch('/api/v1/settings', json={'default_audio_format':'flac','default_audio_quality':'best','account_playlist_method':'api'})
    url = f'https://www.youtube.com/playlist?list={playlist_id}'
    with patch('app.api.youtube_playlists.ytdlp_service.get_playlist_info', return_value={'playlist_id':playlist_id,'playlist_title':'他の人のプレイリスト'}), \
         patch('app.tasks.sync_playlist.sync_youtube_playlist.apply_async'), \
         patch('app.services.youtube_api_service.get_fresh_access_token') as oauth:
        response = client.post('/api/v1/youtube/syncs', json={'source_type':'url','source_url':url})
    assert response.status_code == 201
    assert response.json()['source_type'] == 'url'
    assert response.json()['source_url'] == url
    assert response.json()['audio_format'] == 'flac'
    assert response.json()['audio_quality'] == 'best'
    oauth.assert_not_called()


def test_partial_media_override_keeps_other_saved_default(client):
    client.patch('/api/v1/settings', json={'default_audio_format':'m4a','default_audio_quality':'320'})
    with patch('app.api.urls.resolve_url_task.apply_async'):
        response = client.post('/api/v1/urls', json={'url':'https://youtu.be/jNQXAC9IVRw','audio_format':'ogg'})
    assert response.json()['audio_format'] == 'ogg'
    assert response.json()['audio_quality'] == '320'
