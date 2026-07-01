"""add patient_doctor_request table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-01 19:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "patient_doctor_request",
        sa.Column("patient_detail_id", sa.Integer(), nullable=False),
        sa.Column("doctor_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("PENDING", "APPROVED", "REJECTED", name="request_status_enum"),
            nullable=False,
        ),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("guid", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_modified_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["patient_detail_id"], ["patient_detail.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["doctor_id"], ["doctor_details.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("patient_detail_id", "doctor_id", name="uq_patient_doctor_pair"),
    )
    op.create_index(
        op.f("ix_patient_doctor_request_guid"), "patient_doctor_request", ["guid"], unique=True
    )
    op.create_index(
        op.f("ix_patient_doctor_request_patient_detail_id"),
        "patient_doctor_request",
        ["patient_detail_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_patient_doctor_request_doctor_id"),
        "patient_doctor_request",
        ["doctor_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_patient_doctor_request_status"),
        "patient_doctor_request",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_patient_doctor_request_status"), table_name="patient_doctor_request")
    op.drop_index(op.f("ix_patient_doctor_request_doctor_id"), table_name="patient_doctor_request")
    op.drop_index(
        op.f("ix_patient_doctor_request_patient_detail_id"), table_name="patient_doctor_request"
    )
    op.drop_index(op.f("ix_patient_doctor_request_guid"), table_name="patient_doctor_request")
    op.drop_table("patient_doctor_request")
    # Drop the enum type explicitly (Postgres keeps it after the table is gone).
    sa.Enum(name="request_status_enum").drop(op.get_bind(), checkfirst=True)
