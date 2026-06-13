"""add dir_name to youtube_playlist_syncs

The download directory name is now fixed at sync creation instead of being
recomputed per download, so a sync's files never split across folders when
another sync with the same playlist name is added mid-download.

Existing rows are backfilled to match what the dynamic computation produced:
the sanitized playlist name, with a " [format]" suffix when several syncs
share the same playlist name.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import yt_dlp


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("youtube_playlist_syncs", sa.Column("dir_name", sa.Text(), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, playlist_name, audio_format FROM youtube_playlist_syncs"
    )).fetchall()

    name_counts: dict[str, int] = {}
    for _, playlist_name, _ in rows:
        name_counts[playlist_name] = name_counts.get(playlist_name, 0) + 1

    for sync_id, playlist_name, audio_format in rows:
        base = yt_dlp.utils.sanitize_filename((playlist_name or "").strip(), restricted=False) or "unknown"
        dir_name = f"{base} [{audio_format}]" if name_counts[playlist_name] > 1 else base
        bind.execute(
            sa.text("UPDATE youtube_playlist_syncs SET dir_name = :d WHERE id = :i"),
            {"d": dir_name, "i": sync_id},
        )


def downgrade() -> None:
    op.drop_column("youtube_playlist_syncs", "dir_name")
