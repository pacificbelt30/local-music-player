"""Track playlist download attempts separately from playlist discovery time."""
from alembic import op
import sqlalchemy as sa

revision = '18b9c0d1e2f3'
down_revision = '07a8b9c0d1e2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('playlist_sync_tracks', sa.Column('started_at', sa.DateTime(), nullable=True))
    op.add_column('playlist_sync_tracks', sa.Column('celery_task_id', sa.String(64), nullable=True))


def downgrade():
    with op.batch_alter_table('playlist_sync_tracks') as batch:
        batch.drop_column('celery_task_id')
        batch.drop_column('started_at')
