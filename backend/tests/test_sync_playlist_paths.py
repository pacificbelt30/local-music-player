from app.models import YoutubePlaylistSync
from app.services.sync_dirs import allocate_sync_dir_name, playlist_sync_dir_name


def test_playlist_sync_dir_name_preserves_japanese() -> None:
    assert playlist_sync_dir_name("作業用BGMプレイリスト") == "作業用BGMプレイリスト"


def test_playlist_sync_dir_name_sanitizes_invalid_path_chars() -> None:
    assert playlist_sync_dir_name("My/Playlist:2026") == "My⧸Playlist：2026"


def test_playlist_sync_dir_name_falls_back_for_blank_name() -> None:
    assert playlist_sync_dir_name("   ") == "unknown"


def test_playlist_sync_dir_name_appends_format_suffix() -> None:
    assert playlist_sync_dir_name("My Playlist", "mp4") == "My Playlist [mp4]"


def test_playlist_sync_dir_name_suffix_with_blank_name() -> None:
    assert playlist_sync_dir_name("", "mp3") == "unknown [mp3]"


def _add_sync(db, playlist_id, name, fmt, dir_name=None):
    sync = YoutubePlaylistSync(
        playlist_id=playlist_id, playlist_name=name,
        audio_format=fmt, audio_quality="192", dir_name=dir_name,
    )
    db.add(sync)
    db.commit()
    db.refresh(sync)
    return sync


class TestAllocateSyncDirName:
    def test_first_sync_gets_plain_name(self, db):
        assert allocate_sync_dir_name(db, "Mix", "mp3") == "Mix"

    def test_collision_appends_format(self, db):
        _add_sync(db, "PL1", "Mix", "mp3", dir_name="Mix")
        assert allocate_sync_dir_name(db, "Mix", "mp4") == "Mix [mp4]"

    def test_double_collision_appends_counter(self, db):
        _add_sync(db, "PL1", "Mix", "mp4", dir_name="Mix")
        _add_sync(db, "PL2", "Mix", "mp4", dir_name="Mix [mp4]")
        assert allocate_sync_dir_name(db, "Mix", "mp4") == "Mix [mp4-2]"

    def test_legacy_rows_without_dir_name_still_count_as_taken(self, db):
        _add_sync(db, "PL1", "Mix", "mp3", dir_name=None)
        assert allocate_sync_dir_name(db, "Mix", "mp4") == "Mix [mp4]"

    def test_exclude_id_ignores_own_row(self, db):
        sync = _add_sync(db, "PL1", "Mix", "mp3", dir_name="Mix")
        assert allocate_sync_dir_name(db, "Mix", "m4a", exclude_id=sync.id) == "Mix"
