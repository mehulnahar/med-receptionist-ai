"""Add alternate Fridays columns to practice_configs

Revision ID: f1a2b3c4d5e6
Revises: 68f1cdcfcfcd
Create Date: 2026-03-08 14:30:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = '68f1cdcfcfcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'practice_configs',
        sa.Column('alternate_fridays_enabled', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )
    op.add_column(
        'practice_configs',
        sa.Column('alternate_friday_reference_date', sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('practice_configs', 'alternate_friday_reference_date')
    op.drop_column('practice_configs', 'alternate_fridays_enabled')
