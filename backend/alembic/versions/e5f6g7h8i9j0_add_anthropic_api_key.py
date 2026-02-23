"""Add anthropic_api_key to practice_configs

Revision ID: e5f6g7h8i9j0
Revises: d4e5f6g7h8i9
Create Date: 2026-02-23 12:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'e5f6g7h8i9j0'
down_revision: Union[str, None] = 'd4e5f6g7h8i9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('practice_configs', sa.Column('anthropic_api_key', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('practice_configs', 'anthropic_api_key')
