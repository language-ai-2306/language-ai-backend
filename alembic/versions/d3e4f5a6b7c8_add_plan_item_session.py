"""add plan_item_session (per-occurrence session) + link practice_attempt to it

A plan item recurs (e.g. weekly for months) but is a single row. Each scheduled
occurrence the child practises is now a `plan_item_session` — created lazily on the
first attempt of the day, grouping that day's reps and holding its own status. Every
`practice_attempt` gains `plan_item_session_id` (nullable, SET NULL) alongside the
existing `plan_item_id`.

Backfill: existing planned attempts are grouped by (plan_item, user, day) into
COMPLETED sessions and linked, so history stays consistent.

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-07-02 09:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # create_type=False → the column below won't re-emit CREATE TYPE; we create it
    # once here with checkfirst so the migration is idempotent / re-runnable.
    session_status = postgresql.ENUM(
        "IN_PROGRESS", "COMPLETED", "SKIPPED",
        name="plan_item_session_status_enum",
        create_type=False,
    )
    session_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "plan_item_session",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("guid", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_modified_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("plan_item_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("occurrence_date", sa.Date(), nullable=False),
        sa.Column("status", session_status, nullable=False, server_default="IN_PROGRESS"),
        sa.Column("attempts_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["plan_item_id"], ["plan_item.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("plan_item_id", "occurrence_date", name="uq_session_item_date"),
    )
    op.create_index("ix_plan_item_session_guid", "plan_item_session", ["guid"], unique=True)
    op.create_index("ix_plan_item_session_plan_item_id", "plan_item_session", ["plan_item_id"])
    op.create_index("ix_plan_item_session_user_id", "plan_item_session", ["user_id"])

    # Link column on the unified attempt table.
    op.add_column("practice_attempt", sa.Column("plan_item_session_id", sa.Integer(), nullable=True))
    op.create_index("ix_practice_attempt_plan_item_session_id", "practice_attempt", ["plan_item_session_id"])
    op.create_foreign_key(
        "fk_practice_attempt_plan_item_session",
        "practice_attempt",
        "plan_item_session",
        ["plan_item_session_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Backfill: group existing planned attempts into one COMPLETED session per day.
    op.execute(
        """
        INSERT INTO plan_item_session
            (guid, created_at, last_modified_at, plan_item_id, user_id,
             occurrence_date, status, attempts_count)
        SELECT gen_random_uuid(), MIN(pa.created_at), MAX(pa.created_at),
               pa.plan_item_id, pa.user_id,
               (pa.created_at AT TIME ZONE 'UTC')::date, 'COMPLETED', COUNT(*)
        FROM practice_attempt pa
        WHERE pa.plan_item_id IS NOT NULL
        GROUP BY pa.plan_item_id, pa.user_id, (pa.created_at AT TIME ZONE 'UTC')::date
        """
    )
    op.execute(
        """
        UPDATE practice_attempt pa
        SET plan_item_session_id = s.id
        FROM plan_item_session s
        WHERE pa.plan_item_id = s.plan_item_id
          AND pa.user_id = s.user_id
          AND (pa.created_at AT TIME ZONE 'UTC')::date = s.occurrence_date
        """
    )


def downgrade() -> None:
    op.drop_constraint("fk_practice_attempt_plan_item_session", "practice_attempt", type_="foreignkey")
    op.drop_index("ix_practice_attempt_plan_item_session_id", table_name="practice_attempt")
    op.drop_column("practice_attempt", "plan_item_session_id")

    op.drop_index("ix_plan_item_session_user_id", table_name="plan_item_session")
    op.drop_index("ix_plan_item_session_plan_item_id", table_name="plan_item_session")
    op.drop_index("ix_plan_item_session_guid", table_name="plan_item_session")
    op.drop_table("plan_item_session")
    sa.Enum(name="plan_item_session_status_enum").drop(op.get_bind(), checkfirst=True)
