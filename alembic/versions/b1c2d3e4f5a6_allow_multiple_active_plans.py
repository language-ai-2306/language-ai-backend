"""allow multiple ACTIVE plans per patient (drop the one-active partial unique)

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
Create Date: 2026-07-02 06:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a0b1c2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_practice_plan_one_active_per_patient")


def downgrade() -> None:
    op.create_index(
        "uq_practice_plan_one_active_per_patient",
        "practice_plan",
        ["patient_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
