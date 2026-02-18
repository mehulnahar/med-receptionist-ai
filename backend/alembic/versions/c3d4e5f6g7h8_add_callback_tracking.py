"""Add callback tracking and structured analysis fields to calls.

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2026-02-18 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c3d4e5f6g7h8"
down_revision = "b2c3d4e5f6g7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Callback tracking fields
    op.add_column("calls", sa.Column("callback_needed", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("calls", sa.Column("callback_completed", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("calls", sa.Column("callback_notes", sa.Text(), nullable=True))
    op.add_column("calls", sa.Column("callback_completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("calls", sa.Column("callback_completed_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_calls_callback_user", "calls", "users", ["callback_completed_by"], ["id"])

    # Structured analysis fields (from Vapi analysisPlan)
    op.add_column("calls", sa.Column("structured_data", postgresql.JSONB(), nullable=True))
    op.add_column("calls", sa.Column("success_evaluation", sa.String(20), nullable=True))
    op.add_column("calls", sa.Column("caller_intent", sa.String(50), nullable=True))
    op.add_column("calls", sa.Column("caller_sentiment", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("calls", "caller_sentiment")
    op.drop_column("calls", "caller_intent")
    op.drop_column("calls", "success_evaluation")
    op.drop_column("calls", "structured_data")
    op.drop_constraint("fk_calls_callback_user", "calls", type_="foreignkey")
    op.drop_column("calls", "callback_completed_by")
    op.drop_column("calls", "callback_completed_at")
    op.drop_column("calls", "callback_notes")
    op.drop_column("calls", "callback_completed")
    op.drop_column("calls", "callback_needed")
