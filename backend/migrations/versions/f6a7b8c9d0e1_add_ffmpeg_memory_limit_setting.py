"""add ffmpeg memory limit setting

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SETTING_KEY = "ffmpeg_memory_limit_mb"
_DEFAULT_VALUE = "0"


def upgrade() -> None:
    bind = op.get_bind()
    existing = bind.execute(
        sa.text("SELECT 1 FROM app_settings WHERE key = :key"),
        {"key": _SETTING_KEY},
    ).fetchone()
    if existing is None:
        bind.execute(
            sa.text("INSERT INTO app_settings (key, value) VALUES (:key, :value)"),
            {"key": _SETTING_KEY, "value": _DEFAULT_VALUE},
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM app_settings WHERE key = :key AND value = :value"),
        {"key": _SETTING_KEY, "value": _DEFAULT_VALUE},
    )
