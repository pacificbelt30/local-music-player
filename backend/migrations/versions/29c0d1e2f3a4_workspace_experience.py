"""Persist profiles, destination snapshots and reversible playlist changes."""

from alembic import op
import sqlalchemy as sa

revision = "29c0d1e2f3a4"
down_revision = "18b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "media_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("audio_format", sa.String(10), nullable=False),
        sa.Column("audio_quality", sa.String(10), nullable=False),
        sa.Column("target_folder_id", sa.String(128)),
        sa.Column("target_device_id", sa.String(128)),
        sa.Column(
            "target_scope", sa.String(16), nullable=False, server_default="downloads"
        ),
    )
    for table in ("youtube_playlist_syncs", "url_sources"):
        for name, typ in [
            ("profile_id", sa.Integer()),
            ("profile_name", sa.String(80)),
            ("target_folder_id", sa.String(128)),
            ("target_device_id", sa.String(128)),
        ]:
            op.add_column(table, sa.Column(name, typ, nullable=True))
        op.add_column(
            table,
            sa.Column(
                "target_scope",
                sa.String(16),
                nullable=False,
                server_default="downloads",
            ),
        )
    op.add_column(
        "playlist_sync_tracks", sa.Column("removed_at", sa.DateTime(), nullable=True)
    )
    for name in ("keep_local", "excluded"):
        op.add_column(
            "playlist_sync_tracks",
            sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    op.create_table(
        "sync_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "sync_id",
            sa.Integer(),
            sa.ForeignKey("youtube_playlist_syncs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade():
    op.drop_table("sync_events")
    with op.batch_alter_table("playlist_sync_tracks") as table:
        for name in ("removed_at", "keep_local", "excluded"):
            table.drop_column(name)
    for name in ("youtube_playlist_syncs", "url_sources"):
        with op.batch_alter_table(name) as table:
            for column in (
                "profile_id",
                "profile_name",
                "target_folder_id",
                "target_device_id",
                "target_scope",
            ):
                table.drop_column(column)
    op.drop_table("media_profiles")
