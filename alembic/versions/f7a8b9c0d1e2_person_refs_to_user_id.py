"""point all person references at user.id (patient_id / doctor_id = user.id)

Converts patient_doctor_request, practice_plan, and patient_detail.doctor_id from
referencing doctor_details.id / patient_detail.id to referencing user.id, while
BACKFILLING existing rows so no links are lost. Field names stay semantic
(patient_id = patient's user.id, doctor_id = doctor's user.id).

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-07-02 05:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _drop_fk(table: str, column: str) -> None:
    """Drop whatever FK constraint exists on table.column (name-agnostic)."""
    op.execute(
        f"""
        DO $$
        DECLARE cname text;
        BEGIN
          SELECT con.conname INTO cname
          FROM pg_constraint con
          JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = ANY(con.conkey)
          WHERE con.conrelid = '{table}'::regclass AND con.contype = 'f' AND a.attname = '{column}'
          LIMIT 1;
          IF cname IS NOT NULL THEN EXECUTE 'ALTER TABLE {table} DROP CONSTRAINT ' || quote_ident(cname); END IF;
        END $$;
        """
    )


def upgrade() -> None:
    # ---- patient_doctor_request ------------------------------------------------
    # Drop the old FK BEFORE backfilling (the new value is a user.id, which the old
    # doctor_details FK would reject).
    _drop_fk("patient_doctor_request", "doctor_id")
    op.execute("UPDATE patient_doctor_request r SET doctor_id = d.user_id FROM doctor_details d WHERE r.doctor_id = d.id")
    op.create_foreign_key("fk_pdr_doctor_user", "patient_doctor_request", "user", ["doctor_id"], ["id"], ondelete="CASCADE")

    op.add_column("patient_doctor_request", sa.Column("patient_id", sa.Integer(), nullable=True))
    op.execute("UPDATE patient_doctor_request r SET patient_id = p.user_id FROM patient_detail p WHERE r.patient_detail_id = p.id")
    op.alter_column("patient_doctor_request", "patient_id", nullable=False)
    op.drop_constraint("uq_patient_doctor_pair", "patient_doctor_request", type_="unique")
    _drop_fk("patient_doctor_request", "patient_detail_id")
    op.drop_index("ix_patient_doctor_request_patient_detail_id", table_name="patient_doctor_request")
    op.drop_column("patient_doctor_request", "patient_detail_id")
    op.create_foreign_key("fk_pdr_patient_user", "patient_doctor_request", "user", ["patient_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_patient_doctor_request_patient_id", "patient_doctor_request", ["patient_id"])
    op.create_unique_constraint("uq_patient_doctor_pair", "patient_doctor_request", ["patient_id", "doctor_id"])

    # ---- practice_plan ---------------------------------------------------------
    _drop_fk("practice_plan", "doctor_id")
    op.execute("UPDATE practice_plan pl SET doctor_id = d.user_id FROM doctor_details d WHERE pl.doctor_id = d.id")
    op.create_foreign_key("fk_plan_doctor_user", "practice_plan", "user", ["doctor_id"], ["id"], ondelete="SET NULL")

    op.add_column("practice_plan", sa.Column("patient_id", sa.Integer(), nullable=True))
    op.execute("UPDATE practice_plan pl SET patient_id = p.user_id FROM patient_detail p WHERE pl.patient_detail_id = p.id")
    op.alter_column("practice_plan", "patient_id", nullable=False)
    _drop_fk("practice_plan", "patient_detail_id")
    op.drop_index("ix_practice_plan_patient_detail_id", table_name="practice_plan")
    op.drop_column("practice_plan", "patient_detail_id")
    op.create_foreign_key("fk_plan_patient_user", "practice_plan", "user", ["patient_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_practice_plan_patient_id", "practice_plan", ["patient_id"], unique=True)

    # ---- patient_detail.doctor_id ----------------------------------------------
    _drop_fk("patient_detail", "doctor_id")
    op.execute("UPDATE patient_detail p SET doctor_id = d.user_id FROM doctor_details d WHERE p.doctor_id = d.id")
    op.create_foreign_key("fk_patient_detail_doctor_user", "patient_detail", "user", ["doctor_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    # ---- patient_detail.doctor_id: user.id -> doctor_details.id ----
    _drop_fk("patient_detail", "doctor_id")
    op.execute("UPDATE patient_detail p SET doctor_id = d.id FROM doctor_details d WHERE p.doctor_id = d.user_id")
    op.create_foreign_key(None, "patient_detail", "doctor_details", ["doctor_id"], ["id"], ondelete="SET NULL")

    # ---- practice_plan ----
    op.drop_index("ix_practice_plan_patient_id", table_name="practice_plan")
    _drop_fk("practice_plan", "patient_id")
    op.add_column("practice_plan", sa.Column("patient_detail_id", sa.Integer(), nullable=True))
    op.execute("UPDATE practice_plan pl SET patient_detail_id = p.id FROM patient_detail p WHERE pl.patient_id = p.user_id")
    op.alter_column("practice_plan", "patient_detail_id", nullable=False)
    op.drop_column("practice_plan", "patient_id")
    op.create_foreign_key(None, "practice_plan", "patient_detail", ["patient_detail_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_practice_plan_patient_detail_id", "practice_plan", ["patient_detail_id"], unique=True)
    _drop_fk("practice_plan", "doctor_id")
    op.execute("UPDATE practice_plan pl SET doctor_id = d.id FROM doctor_details d WHERE pl.doctor_id = d.user_id")
    op.create_foreign_key(None, "practice_plan", "doctor_details", ["doctor_id"], ["id"], ondelete="SET NULL")

    # ---- patient_doctor_request ----
    op.drop_constraint("uq_patient_doctor_pair", "patient_doctor_request", type_="unique")
    op.drop_index("ix_patient_doctor_request_patient_id", table_name="patient_doctor_request")
    _drop_fk("patient_doctor_request", "patient_id")
    op.add_column("patient_doctor_request", sa.Column("patient_detail_id", sa.Integer(), nullable=True))
    op.execute("UPDATE patient_doctor_request r SET patient_detail_id = p.id FROM patient_detail p WHERE r.patient_id = p.user_id")
    op.alter_column("patient_doctor_request", "patient_detail_id", nullable=False)
    op.drop_column("patient_doctor_request", "patient_id")
    op.create_foreign_key(None, "patient_doctor_request", "patient_detail", ["patient_detail_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_patient_doctor_request_patient_detail_id", "patient_doctor_request", ["patient_detail_id"])
    op.create_unique_constraint("uq_patient_doctor_pair", "patient_doctor_request", ["patient_detail_id", "doctor_id"])
    _drop_fk("patient_doctor_request", "doctor_id")
    op.execute("UPDATE patient_doctor_request r SET doctor_id = d.id FROM doctor_details d WHERE r.doctor_id = d.user_id")
    op.create_foreign_key(None, "patient_doctor_request", "doctor_details", ["doctor_id"], ["id"], ondelete="CASCADE")
