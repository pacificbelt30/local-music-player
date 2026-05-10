"""add last_error to youtube_playlist_syncs

Revision ID: a1b2c3d4e5f6
Revises: d8524591de41
Create Date: 2026-05-10 05:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'd8524591de41'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('youtube_playlist_syncs', sa.Column('last_error', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('youtube_playlist_syncs', 'last_error')
