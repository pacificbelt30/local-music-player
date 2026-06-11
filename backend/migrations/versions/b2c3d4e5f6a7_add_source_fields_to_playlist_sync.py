"""add source_type and source_url to youtube_playlist_syncs

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {col["name"] for col in inspector.get_columns("youtube_playlist_syncs")}
    if "source_type" not in existing_cols:
        op.add_column("youtube_playlist_syncs", sa.Column("source_type", sa.String(8), nullable=False, server_default="api"))
    if "source_url" not in existing_cols:
        op.add_column("youtube_playlist_syncs", sa.Column("source_url", sa.String(2048), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column('youtube_playlist_syncs', 'source_url')
    op.drop_column('youtube_playlist_syncs', 'source_type')
