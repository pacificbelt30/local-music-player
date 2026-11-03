"""Index playlist ordering for bounded detail pages."""

from alembic import op

revision = "3ad1e2f3a4b5"
down_revision = "29c0d1e2f3a4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_sync_tracks_position",
        "playlist_sync_tracks",
        ["playlist_sync_id", "position", "id"],
    )


def downgrade():
    op.drop_index("ix_sync_tracks_position", table_name="playlist_sync_tracks")
