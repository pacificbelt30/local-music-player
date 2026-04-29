import pytest
from pydantic import ValidationError

from app.schemas import UrlSourceCreate, TrackUpdate, DownloadJobResponse, TrackResponse


class TestUrlSourceCreate:
    def test_valid_youtube_com_url(self):
        s = UrlSourceCreate(url="https://www.youtube.com/watch?v=abc123")
        assert s.url == "https://www.youtube.com/watch?v=abc123"

    def test_valid_youtu_be_url(self):
        s = UrlSourceCreate(url="https://youtu.be/abc123")
        assert s.url == "https://youtu.be/abc123"

    def test_non_youtube_url_raises(self):
        with pytest.raises(ValidationError):
            UrlSourceCreate(url="https://example.com/video")

    def test_default_format_is_mp3(self):
        s = UrlSourceCreate(url="https://youtu.be/abc")
        assert s.audio_format == "mp3"

    def test_default_quality_is_192(self):
        s = UrlSourceCreate(url="https://youtu.be/abc")
        assert s.audio_quality == "192"

    def test_default_sync_enabled(self):
        s = UrlSourceCreate(url="https://youtu.be/abc")
        assert s.sync_enabled is True

    def test_flac_format(self):
        s = UrlSourceCreate(url="https://youtu.be/abc", audio_format="flac")
        assert s.audio_format == "flac"

    def test_best_quality(self):
        s = UrlSourceCreate(url="https://youtu.be/abc", audio_quality="best")
        assert s.audio_quality == "best"

    def test_320_quality(self):
        s = UrlSourceCreate(url="https://youtu.be/abc", audio_quality="320")
        assert s.audio_quality == "320"

    def test_invalid_format_raises(self):
        with pytest.raises(ValidationError):
            UrlSourceCreate(url="https://youtu.be/abc", audio_format="wav")

    def test_invalid_quality_raises(self):
        with pytest.raises(ValidationError):
            UrlSourceCreate(url="https://youtu.be/abc", audio_quality="128")


class TestTrackUpdate:
    def test_all_none_by_default(self):
        u = TrackUpdate()
        assert u.title is None
        assert u.artist is None
        assert u.album is None

    def test_partial_update(self):
        u = TrackUpdate(title="New Title")
        assert u.title == "New Title"
        assert u.artist is None

    def test_model_dump_excludes_none(self):
        u = TrackUpdate(title="T")
        dumped = u.model_dump(exclude_none=True)
        assert "title" in dumped
        assert "artist" not in dumped
