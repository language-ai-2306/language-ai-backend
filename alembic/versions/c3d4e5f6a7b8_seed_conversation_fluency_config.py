"""seed fluency-supportive conversation config (phase 3)

Revision ID: c3d4e5f6a7b8
Revises: b2f3c4d5e6a7
Create Date: 2026-06-29 03:45:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2f3c4d5e6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KEYS = ["conversation_fluency_support", "conversation_response_latency_ms"]


def upgrade() -> None:
    op.execute(
        sa.text("""
        INSERT INTO app_config
            (guid, key, value, value_type, description, is_editable, created_at, last_modified_at)
        VALUES
            (gen_random_uuid(), 'conversation_fluency_support', 'true', 'bool',
             'Apply the fluency-supportive (low communicative-demand) conversation policy for Ollie',
             true, now(), now()),
            (gen_random_uuid(), 'conversation_response_latency_ms', '1500', 'int',
             'Frontend hint: pause this many ms before playing Ollie''s reply, and never interrupt the child',
             true, now(), now())
        """)
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM app_config WHERE key IN :keys").bindparams(
            sa.bindparam("keys", _KEYS, expanding=True)
        )
    )
