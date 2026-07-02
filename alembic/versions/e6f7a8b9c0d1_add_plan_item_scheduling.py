"""add plan_item scheduling (frequency, duration, schedule) + one-plan-per-patient

Idempotent (IF NOT EXISTS / DROP IF EXISTS) so it's safe on databases where these
columns were already added by hand. Applied automatically on server startup.

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-07-02 04:30:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE plan_item ADD COLUMN IF NOT EXISTS frequency VARCHAR(10) NOT NULL DEFAULT 'DAILY'")
    op.execute("ALTER TABLE plan_item ADD COLUMN IF NOT EXISTS duration_minutes INTEGER")
    op.execute("ALTER TABLE plan_item ADD COLUMN IF NOT EXISTS schedule JSONB NOT NULL DEFAULT '{}'::jsonb")
    # one plan per patient — make the patient_detail_id index unique
    op.execute("DROP INDEX IF EXISTS ix_practice_plan_patient_detail_id")
    op.execute("CREATE UNIQUE INDEX ix_practice_plan_patient_detail_id ON practice_plan (patient_detail_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_practice_plan_patient_detail_id")
    op.execute("CREATE INDEX ix_practice_plan_patient_detail_id ON practice_plan (patient_detail_id)")
    op.execute("ALTER TABLE plan_item DROP COLUMN IF EXISTS schedule")
    op.execute("ALTER TABLE plan_item DROP COLUMN IF EXISTS duration_minutes")
    op.execute("ALTER TABLE plan_item DROP COLUMN IF EXISTS frequency")
