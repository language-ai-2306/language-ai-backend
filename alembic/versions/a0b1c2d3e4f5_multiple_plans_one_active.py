"""allow multiple plans per patient, but only one ACTIVE at a time

Replaces the blanket unique(patient_id) on practice_plan with a PARTIAL unique
index that only applies to ACTIVE plans — so a patient can accumulate
DRAFT/COMPLETED/ARCHIVED plans (history) while at most one is ACTIVE.

Revision ID: a0b1c2d3e4f5
Revises: f7a8b9c0d1e2
Create Date: 2026-07-02 06:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a0b1c2d3e4f5"
down_revision: Union[str, None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Was unique — make it a plain index (patient may have many plans now).
    op.drop_index("ix_practice_plan_patient_id", table_name="practice_plan")
    op.create_index("ix_practice_plan_patient_id", "practice_plan", ["patient_id"])
    # Enforce "one ACTIVE plan per patient" at the DB level.
    op.create_index(
        "uq_practice_plan_one_active_per_patient",
        "practice_plan",
        ["patient_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )


def downgrade() -> None:
    op.drop_index("uq_practice_plan_one_active_per_patient", table_name="practice_plan")
    op.drop_index("ix_practice_plan_patient_id", table_name="practice_plan")
    op.create_index("ix_practice_plan_patient_id", "practice_plan", ["patient_id"], unique=True)
