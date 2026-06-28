"""add conversation_history table

Revision ID: 3c2e068d5a8e
Revises: 6c7f011e9823
Create Date: 2026-06-28 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3c2e068d5a8e"
down_revision: Union[str, None] = "6c7f011e9823"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversation_history",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column("child_transcript", sa.Text(), nullable=True),
        sa.Column("child_audio_url", sa.Text(), nullable=True),
        sa.Column("ai_text", sa.Text(), nullable=True),
        sa.Column("ai_audio_url", sa.Text(), nullable=True),
        sa.Column("disfluency_events", postgresql.JSONB(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("guid", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_modified_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversation_history_guid", "conversation_history", ["guid"], unique=True)
    op.create_index("ix_conversation_history_user_id", "conversation_history", ["user_id"], unique=False)
    op.create_index("ix_conversation_history_session_id", "conversation_history", ["session_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_conversation_history_session_id", table_name="conversation_history")
    op.drop_index("ix_conversation_history_user_id", table_name="conversation_history")
    op.drop_index("ix_conversation_history_guid", table_name="conversation_history")
    op.drop_table("conversation_history")
