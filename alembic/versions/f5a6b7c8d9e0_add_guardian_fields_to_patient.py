"""add guardian_name / guardian_relationship / guardian_email to patient_detail

Collected for minors at signup; nullable (adults leave them blank).

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-07-03 08:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f5a6b7c8d9e0"
down_revision: Union[str, None] = "e4f5a6b7c8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("patient_detail", sa.Column("guardian_name", sa.String(length=100), nullable=True))
    op.add_column("patient_detail", sa.Column("guardian_relationship", sa.String(length=32), nullable=True))
    op.add_column("patient_detail", sa.Column("guardian_email", sa.String(length=320), nullable=True))


def downgrade() -> None:
    op.drop_column("patient_detail", "guardian_email")
    op.drop_column("patient_detail", "guardian_relationship")
    op.drop_column("patient_detail", "guardian_name")
