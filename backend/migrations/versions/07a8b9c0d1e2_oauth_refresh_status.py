"""Persist refresh-token diagnostics; legacy lifetimes stay unknown."""
from alembic import op
import sqlalchemy as sa

revision = '07a8b9c0d1e2'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade():
    for name in ('authorized_at', 'refresh_token_expiry', 'last_refresh_at'):
        op.add_column('youtube_oauth_tokens', sa.Column(name, sa.DateTime(), nullable=True))
    op.add_column('youtube_oauth_tokens', sa.Column('refresh_error', sa.String(64), nullable=True))


def downgrade():
    with op.batch_alter_table('youtube_oauth_tokens') as batch:
        for name in ('refresh_error', 'last_refresh_at', 'refresh_token_expiry', 'authorized_at'):
            batch.drop_column(name)
