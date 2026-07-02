"""add practice plan tables (practice_plan, plan_item, plan_item_attempt)

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-07-02 03:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# difficulty_enum already exists — reference it, don't recreate.
_difficulty = postgresql.ENUM(
    "EASY", "MEDIUM", "HARD", "TONGUE_TWISTER", name="difficulty_enum", create_type=False
)
_plan_status = postgresql.ENUM(
    "DRAFT", "ACTIVE", "COMPLETED", "ARCHIVED", name="plan_status_enum", create_type=False
)
_item_status = postgresql.ENUM(
    "LOCKED", "ACTIVE", "COMPLETED", name="plan_item_status_enum", create_type=False
)

_ABSTRACT_COLS = [
    ("id", sa.Integer(), dict(autoincrement=True, nullable=False)),
    ("guid", sa.UUID(), dict(nullable=False)),
    ("created_at", sa.DateTime(timezone=True), dict(server_default=sa.text("now()"), nullable=False)),
    ("last_modified_at", sa.DateTime(timezone=True), dict(server_default=sa.text("now()"), nullable=False)),
    ("created_by", sa.String(length=255), dict(nullable=True)),
]


def _abstract():
    return [sa.Column(n, t, **kw) for n, t, kw in _ABSTRACT_COLS]


def upgrade() -> None:
    _plan_status.create(op.get_bind(), checkfirst=True)
    _item_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "practice_plan",
        sa.Column("patient_detail_id", sa.Integer(), nullable=False),
        sa.Column("doctor_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", _plan_status, nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        *_abstract(),
        sa.ForeignKeyConstraint(["patient_detail_id"], ["patient_detail.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["doctor_id"], ["doctor_details.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_practice_plan_guid"), "practice_plan", ["guid"], unique=True)
    op.create_index(op.f("ix_practice_plan_patient_detail_id"), "practice_plan", ["patient_detail_id"])
    op.create_index(op.f("ix_practice_plan_status"), "practice_plan", ["status"])

    op.create_table(
        "plan_item",
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("exercise_type", sa.String(length=20), nullable=False),
        sa.Column("target_phoneme", sa.String(length=16), nullable=True),
        sa.Column("difficulty", _difficulty, nullable=True),
        sa.Column("dosage", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("advancement", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", _item_status, nullable=False),
        *_abstract(),
        sa.ForeignKeyConstraint(["plan_id"], ["practice_plan.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_plan_item_guid"), "plan_item", ["guid"], unique=True)
    op.create_index(op.f("ix_plan_item_plan_id"), "plan_item", ["plan_id"])

    op.create_table(
        "plan_item_attempt",
        sa.Column("plan_item_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("fluency_score", sa.Float(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        *_abstract(),
        sa.ForeignKeyConstraint(["plan_item_id"], ["plan_item.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_plan_item_attempt_guid"), "plan_item_attempt", ["guid"], unique=True)
    op.create_index(op.f("ix_plan_item_attempt_plan_item_id"), "plan_item_attempt", ["plan_item_id"])
    op.create_index(op.f("ix_plan_item_attempt_user_id"), "plan_item_attempt", ["user_id"])


def downgrade() -> None:
    op.drop_table("plan_item_attempt")
    op.drop_table("plan_item")
    op.drop_table("practice_plan")
    sa.Enum(name="plan_item_status_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="plan_status_enum").drop(op.get_bind(), checkfirst=True)
