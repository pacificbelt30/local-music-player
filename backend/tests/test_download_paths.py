from pathlib import Path

from app.models import UrlSource
from app.tasks.download import _download_base_path


def test_download_base_path_uses_manual_dir_for_missing_source(monkeypatch, tmp_path):
    monkeypatch.setattr("app.tasks.download.settings.downloads_path", tmp_path)

    path = _download_base_path(None)

    assert path == tmp_path / "manual"


def test_download_base_path_sanitizes_playlist_name(monkeypatch, tmp_path):
    monkeypatch.setattr("app.tasks.download.settings.downloads_path", tmp_path)
    source = UrlSource(id=1, url="https://example.com", url_type="playlist", title="My/Playlist:2026")

    path = _download_base_path(source)

    assert path == tmp_path / "My_Playlist_-2026"
