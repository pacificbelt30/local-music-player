"""A Last.fm play link is resolved without following or downloading its video."""

from unittest.mock import MagicMock

import pytest

from app.services import ytdlp_service


def test_lastfm_source_is_metadata_only_and_canonicalizes_one_video(monkeypatch):
    client = MagicMock()
    client.__enter__.return_value.extract_info.return_value = {
        "_type": "url",
        "url": "https://www.youtube.com/watch?v=jNQXAC9IVRw&list=ignored",
    }
    constructor = MagicMock(return_value=client)
    monkeypatch.setattr(ytdlp_service.yt_dlp, "YoutubeDL", constructor)
    result = ytdlp_service.resolve_lastfm_track("A/B", "Song & music")
    assert result == "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    client.__enter__.return_value.extract_info.assert_called_once_with(
        "https://www.last.fm/music/A%2FB/_/Song%20%26%20music",
        download=False,
        process=False,
        ie_key="LastFM",
    )
    assert constructor.call_args.args[0]["skip_download"] is True


@pytest.mark.parametrize(
    "url",
    [
        None,
        "https://evil.example/video",
        "https://www.youtube.com/playlist?list=abc",
        "javascript:alert(1)",
        "https://www.youtube.com/watch?v=bad",
    ],
)
def test_invalid_lastfm_play_link_is_rejected(monkeypatch, url):
    client = MagicMock()
    client.__enter__.return_value.extract_info.return_value = {"url": url}
    monkeypatch.setattr(ytdlp_service.yt_dlp, "YoutubeDL", lambda opts: client)
    with pytest.raises(ValueError):
        ytdlp_service.resolve_lastfm_track("Artist", "Song")


def test_source_lookup_uses_the_managed_ytdlp_installation(monkeypatch):
    from app.services import ytdlp_process

    monkeypatch.delenv("YTDLP_CHILD")
    call = MagicMock(return_value="https://www.youtube.com/watch?v=jNQXAC9IVRw")
    monkeypatch.setattr(ytdlp_process, "call", call)
    ytdlp_service.resolve_lastfm_track("Artist", "Song")
    call.assert_called_once_with(
        "resolve_lastfm_track", {"artist": "Artist", "track": "Song"}, timeout=30
    )
