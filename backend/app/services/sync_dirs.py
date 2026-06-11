"""Directory naming for playlist sync downloads."""
import yt_dlp
from sqlalchemy.orm import Session


def playlist_sync_dir_name(playlist_name: str | None, format_suffix: str | None = None) -> str:
    """Build a safe directory name while preserving non-ASCII playlist names.

    When the same playlist is synced in multiple formats the directory name
    would collide, so the format is appended as a suffix (e.g. "Mix [mp4]").
    """
    name = (playlist_name or "").strip()
    base = yt_dlp.utils.sanitize_filename(name, restricted=False) or "unknown"
    if format_suffix:
        return f"{base} [{format_suffix}]"
    return base


def allocate_sync_dir_name(db: Session, playlist_name: str, audio_format: str, exclude_id: int | None = None) -> str:
    """Pick a directory name not used by any other sync, fixed at sync creation.

    The plain playlist name is preferred; on collision the format is appended,
    then a numbered format suffix as a last resort.
    """
    from app.models import YoutubePlaylistSync

    query = db.query(YoutubePlaylistSync.playlist_name, YoutubePlaylistSync.dir_name)
    if exclude_id is not None:
        query = query.filter(YoutubePlaylistSync.id != exclude_id)
    taken = {
        other_dir or playlist_sync_dir_name(other_name)
        for other_name, other_dir in query.all()
    }

    candidate = playlist_sync_dir_name(playlist_name)
    if candidate not in taken:
        return candidate
    candidate = playlist_sync_dir_name(playlist_name, audio_format)
    counter = 2
    while candidate in taken:
        candidate = playlist_sync_dir_name(playlist_name, f"{audio_format}-{counter}")
        counter += 1
    return candidate
