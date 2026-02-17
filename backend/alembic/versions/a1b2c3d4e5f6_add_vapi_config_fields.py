"""Add Vapi config fields to practice_configs

Revision ID: a1b2c3d4e5f6
Revises: 0862cae43115
Create Date: 2026-02-17 18:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '0862cae43115'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('practice_configs', sa.Column('vapi_phone_number_id', sa.String(length=100), nullable=True))
    op.add_column('practice_configs', sa.Column('vapi_system_prompt', sa.Text(), nullable=True))
    op.add_column('practice_configs', sa.Column('vapi_first_message', sa.Text(), nullable=True))
    op.add_column('practice_configs', sa.Column('vapi_model_provider', sa.String(length=50), nullable=False, server_default='openai'))
    op.add_column('practice_configs', sa.Column('vapi_model_name', sa.String(length=50), nullable=False, server_default='gpt-4o-mini'))
    op.add_column('practice_configs', sa.Column('vapi_voice_provider', sa.String(length=50), nullable=False, server_default='11labs'))
    op.add_column('practice_configs', sa.Column('vapi_voice_id', sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column('practice_configs', 'vapi_voice_id')
    op.drop_column('practice_configs', 'vapi_voice_provider')
    op.drop_column('practice_configs', 'vapi_model_name')
    op.drop_column('practice_configs', 'vapi_model_provider')
    op.drop_column('practice_configs', 'vapi_first_message')
    op.drop_column('practice_configs', 'vapi_system_prompt')
    op.drop_column('practice_configs', 'vapi_phone_number_id')
