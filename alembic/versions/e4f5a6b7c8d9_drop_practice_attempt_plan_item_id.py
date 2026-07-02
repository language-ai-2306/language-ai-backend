"""drop practice_attempt.plan_item_id — redundant with plan_item_session_id

The plan item is reached through the session (plan_item_session.plan_item_id), so a
duplicate plan_item_id on practice_attempt is unnecessary. Before dropping it, any
attempt that still has plan_item_id but no session (e.g. rows written by an older
build) is backfilled into a session so no plan link is lost.

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-07-02 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4f5a6b7c8d9"
down_revision: Union[str, None] = "d3e4f5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Rescue any attempts still tagged by plan_item_id but not linked to a session.
    op.execute(
        """
        INSERT INTO plan_item_session
            (guid, created_at, last_modified_at, plan_item_id, user_id,
             occurrence_date, status, attempts_count)
        SELECT gen_random_uuid(), MIN(pa.created_at), MAX(pa.created_at),
               pa.plan_item_id, pa.user_id,
               (pa.created_at AT TIME ZONE 'UTC')::date, 'IN_PROGRESS', COUNT(*)
        FROM practice_attempt pa
        WHERE pa.plan_item_id IS NOT NULL AND pa.plan_item_session_id IS NULL
        GROUP BY pa.plan_item_id, pa.user_id, (pa.created_at AT TIME ZONE 'UTC')::date
        ON CONFLICT (plan_item_id, occurrence_date) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE practice_attempt pa
        SET plan_item_session_id = s.id
        FROM plan_item_session s
        WHERE pa.plan_item_session_id IS NULL
          AND pa.plan_item_id IS NOT NULL
          AND pa.plan_item_id = s.plan_item_id
          AND pa.user_id = s.user_id
          AND (pa.created_at AT TIME ZONE 'UTC')::date = s.occurrence_date
        """
    )

    # 2. Drop the redundant column (+ its FK / index).
    op.execute("ALTER TABLE practice_attempt DROP CONSTRAINT IF EXISTS fk_practice_attempt_plan_item")
    op.execute("DROP INDEX IF EXISTS ix_practice_attempt_plan_item_id")
    op.drop_column("practice_attempt", "plan_item_id")


def downgrade() -> None:
    op.add_column("practice_attempt", sa.Column("plan_item_id", sa.Integer(), nullable=True))
    op.create_index("ix_practice_attempt_plan_item_id", "practice_attempt", ["plan_item_id"])
    op.create_foreign_key(
        "fk_practice_attempt_plan_item",
        "practice_attempt",
        "plan_item",
        ["plan_item_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Rebuild the denormalized value from the session link.
    op.execute(
        """
        UPDATE practice_attempt pa
        SET plan_item_id = s.plan_item_id
        FROM plan_item_session s
        WHERE pa.plan_item_session_id = s.id
        """
    )
