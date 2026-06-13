"""Directory naming for playlist sync downloads."""
import os

import yt_dlp
from sqlalchemy.orm import Session

from app.config import settings


def playlist_sync_dir_name(playlist_name: str | None, format_suffix: str | None = None) -> str:
    """Build a safe directory name while preserving non-ASCII playlist names.

    When the same playlist name is synced in multiple formats the directory
    name carries the format as a suffix (e.g. "Mix [mp4]").
    """
    name = (playlist_name or "").strip()
    base = yt_dlp.utils.sanitize_filename(name, restricted=False) or "unknown"
    if format_suffix:
        return f"{base} [{format_suffix}]"
    return base


def allocate_sync_dir_name(db: Session, playlist_name: str, audio_format: str, exclude_id: int | None = None) -> str:
    """Pick a directory name for a sync, fixed at sync creation.

    A sync that is alone with its playlist name gets the plain name; as soon
    as another sync shares the name, every sync of that name carries its
    format as a suffix (a numbered suffix disambiguates same-format clashes).
    """
    from app.models import YoutubePlaylistSync

    query = db.query(YoutubePlaylistSync.playlist_name, YoutubePlaylistSync.dir_name)
    if exclude_id is not None:
        query = query.filter(YoutubePlaylistSync.id != exclude_id)

    base = playlist_sync_dir_name(playlist_name)
    has_same_name = False
    taken = set()
    for other_name, other_dir in query.all():
        taken.add(other_dir or playlist_sync_dir_name(other_name))
        if playlist_sync_dir_name(other_name) == base:
            has_same_name = True

    if not has_same_name and base not in taken:
        return base

    candidate = playlist_sync_dir_name(playlist_name, audio_format)
    counter = 2
    while candidate in taken:
        candidate = playlist_sync_dir_name(playlist_name, f"{audio_format}-{counter}")
        counter += 1
    return candidate


def relabel_sync_dir(db: Session, sync, new_dir_name: str) -> None:
    """Move a sync to a new directory name, renaming the folder on disk and
    rewriting the stored file paths of its tracks.

    If the folder cannot be renamed (e.g. the target already exists), the old
    name is kept so the directory and the tracked file paths stay consistent.
    """
    from app.models import PlaylistSyncTrack

    old_name = sync.dir_name
    if old_name == new_dir_name:
        return
    if not old_name:
        sync.dir_name = new_dir_name
        return

    old_dir = settings.downloads_path / old_name
    new_dir = settings.downloads_path / new_dir_name
    if old_dir.is_dir():
        try:
            if new_dir.exists():
                return
            old_dir.rename(new_dir)
        except OSError:
            return
        old_prefix = str(old_dir) + os.sep
        tracks = db.query(PlaylistSyncTrack).filter_by(playlist_sync_id=sync.id).all()
        for track in tracks:
            for attr in ("file_path", "thumbnail_path"):
                value = getattr(track, attr)
                if value and value.startswith(old_prefix):
                    setattr(track, attr, str(new_dir) + value[len(str(old_dir)):])

    sync.dir_name = new_dir_name
