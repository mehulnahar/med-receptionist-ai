"""Add configurable settings fields to practice_configs

Revision ID: 68f1cdcfcfcd
Revises: e5f6g7h8i9j0
Create Date: 2026-03-08 13:46:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '68f1cdcfcfcd'
down_revision: Union[str, None] = 'e5f6g7h8i9j0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('practice_configs', sa.Column('transfer_message', sa.Text(), nullable=True))
    op.add_column('practice_configs', sa.Column('fallback_phone_number', sa.String(20), nullable=True))
    op.add_column('practice_configs', sa.Column(
        'reminder_template_24h',
        sa.JSON(),
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    ))
    op.add_column('practice_configs', sa.Column(
        'reminder_template_2h',
        sa.JSON(),
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    ))


def downgrade() -> None:
    op.drop_column('practice_configs', 'reminder_template_2h')
    op.drop_column('practice_configs', 'reminder_template_24h')
    op.drop_column('practice_configs', 'fallback_phone_number')
    op.drop_column('practice_configs', 'transfer_message')
