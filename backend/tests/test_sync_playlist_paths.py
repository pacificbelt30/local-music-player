from app.tasks.sync_playlist import _playlist_sync_dir_name


def test_playlist_sync_dir_name_preserves_japanese() -> None:
    assert _playlist_sync_dir_name("作業用BGMプレイリスト") == "作業用BGMプレイリスト"


def test_playlist_sync_dir_name_sanitizes_invalid_path_chars() -> None:
    assert _playlist_sync_dir_name("My/Playlist:2026") == "My⧸Playlist：2026"


def test_playlist_sync_dir_name_falls_back_for_blank_name() -> None:
    assert _playlist_sync_dir_name("   ") == "unknown"
