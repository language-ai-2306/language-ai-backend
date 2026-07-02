"""add exercise_type column to disfluency_phrase

Adds a plain-string `exercise_type` to disfluency_phrase so the same table can
hold content for every game. The server_default backfills all existing rows to
'REPEAT_AFTER_ME' in a single statement.

Revision ID: b3c4d5e6f7a8
Revises: d4e5f6a7b8c9
Create Date: 2026-07-02 01:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "disfluency_phrase",
        sa.Column(
            "exercise_type",
            sa.String(length=20),
            nullable=False,
            server_default="REPEAT_AFTER_ME",  # backfills every existing row
        ),
    )
    op.create_index(
        op.f("ix_disfluency_phrase_exercise_type"),
        "disfluency_phrase",
        ["exercise_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_disfluency_phrase_exercise_type"), table_name="disfluency_phrase")
    op.drop_column("disfluency_phrase", "exercise_type")
