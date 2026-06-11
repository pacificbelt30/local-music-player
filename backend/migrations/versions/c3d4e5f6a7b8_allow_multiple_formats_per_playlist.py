"""allow multiple formats per playlist sync

Replace the unique constraint on youtube_playlist_syncs.playlist_id with a
composite unique constraint on (playlist_id, audio_format) so the same
playlist can be synced once per format (e.g. mp3 + mp4).

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_def(metadata: sa.MetaData, *constraints: sa.UniqueConstraint) -> sa.Table:
    return sa.Table(
        "youtube_playlist_syncs", metadata,
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("playlist_id", sa.String(length=64), nullable=False),
        sa.Column("playlist_name", sa.Text(), nullable=False),
        sa.Column("audio_format", sa.String(length=10), nullable=False),
        sa.Column("audio_quality", sa.String(length=10), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("source_type", sa.String(length=8), nullable=False, server_default="api"),
        sa.Column("source_url", sa.String(length=2048), nullable=False, server_default=""),
        sa.Column("last_synced", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        *constraints,
    )


def upgrade() -> None:
    # SQLite cannot drop constraints in place; batch mode recreates the table
    # from copy_from, which intentionally omits the old UNIQUE(playlist_id).
    table = _table_def(sa.MetaData())
    with op.batch_alter_table("youtube_playlist_syncs", copy_from=table) as batch:
        batch.create_unique_constraint(
            "uq_playlist_syncs_playlist_id_format", ["playlist_id", "audio_format"]
        )


def downgrade() -> None:
    table = _table_def(
        sa.MetaData(),
        sa.UniqueConstraint("playlist_id", "audio_format", name="uq_playlist_syncs_playlist_id_format"),
    )
    with op.batch_alter_table("youtube_playlist_syncs", copy_from=table) as batch:
        batch.drop_constraint("uq_playlist_syncs_playlist_id_format", type_="unique")
        batch.create_unique_constraint("uq_playlist_syncs_playlist_id", ["playlist_id"])
