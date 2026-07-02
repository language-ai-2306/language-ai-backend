"""unify attempts: add exercise_type + plan_item_id to practice_attempt, drop plan_item_attempt

Every exercise attempt (any game, free or planned) is now a single `practice_attempt`
row. A planned attempt carries `plan_item_id` (the marker); free play leaves it NULL.
`ON DELETE SET NULL` so deleting a plan preserves the child's fluency history.

The old parallel `plan_item_attempt` table is retired: its rows are migrated into
`practice_attempt` (mapping the stored `result` JSONB back into columns), then the
table is dropped.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-07-02 08:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. New columns on the unified attempt table.
    op.add_column("practice_attempt", sa.Column("exercise_type", sa.String(length=20), nullable=True))
    op.add_column("practice_attempt", sa.Column("plan_item_id", sa.Integer(), nullable=True))
    op.create_index("ix_practice_attempt_exercise_type", "practice_attempt", ["exercise_type"])
    op.create_index("ix_practice_attempt_plan_item_id", "practice_attempt", ["plan_item_id"])
    op.create_foreign_key(
        "fk_practice_attempt_plan_item",
        "practice_attempt",
        "plan_item",
        ["plan_item_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 2. Every existing practice_attempt row was Repeat After Me.
    op.execute("UPDATE practice_attempt SET exercise_type = 'REPEAT_AFTER_ME' WHERE exercise_type IS NULL")

    # 3. Migrate plan_item_attempt history into practice_attempt, reconstructing the
    #    promoted columns from the stored `result` JSONB. exercise_type comes from the
    #    linked plan item. reference_phrase is NOT NULL → COALESCE to ''.
    op.execute(
        """
        INSERT INTO practice_attempt
            (guid, created_at, last_modified_at, created_by,
             user_id, phrase_id, exercise_type, plan_item_id,
             reference_phrase, transcript, audio_url,
             fluency_score, coverage_score, stutter_frequency_percent, words_per_minute,
             dominant_disfluency, should_retry, child_age,
             disfluencies, recognition, scores)
        SELECT
            gen_random_uuid(), pia.attempted_at, pia.attempted_at, pia.created_by,
            pia.user_id, NULL, pi.exercise_type, pia.plan_item_id,
            COALESCE(pia.result->>'reference_phrase', ''),
            pia.result->>'transcript', NULL,
            pia.fluency_score,
            (pia.result#>>'{scores,coverage_score}')::float,
            (pia.result#>>'{scores,stutter_frequency_percent}')::float,
            (pia.result#>>'{scores,words_per_minute}')::float,
            pia.result#>>'{recognition,dominant_disfluency}',
            (pia.result->>'should_retry')::boolean,
            NULL,
            pia.result->'disfluencies', pia.result->'recognition', pia.result->'scores'
        FROM plan_item_attempt pia
        JOIN plan_item pi ON pi.id = pia.plan_item_id
        """
    )

    # 4. Retire the parallel table.
    op.drop_table("plan_item_attempt")


def downgrade() -> None:
    # Recreate the retired table (structure only — data is not migrated back).
    op.create_table(
        "plan_item_attempt",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("guid", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_modified_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("plan_item_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("fluency_score", sa.Float(), nullable=True),
        sa.Column("result", JSONB(), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plan_item_id"], ["plan_item.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_plan_item_attempt_guid", "plan_item_attempt", ["guid"], unique=True)
    op.create_index("ix_plan_item_attempt_plan_item_id", "plan_item_attempt", ["plan_item_id"])
    op.create_index("ix_plan_item_attempt_user_id", "plan_item_attempt", ["user_id"])

    op.drop_constraint("fk_practice_attempt_plan_item", "practice_attempt", type_="foreignkey")
    op.drop_index("ix_practice_attempt_plan_item_id", table_name="practice_attempt")
    op.drop_index("ix_practice_attempt_exercise_type", table_name="practice_attempt")
    op.drop_column("practice_attempt", "plan_item_id")
    op.drop_column("practice_attempt", "exercise_type")
