"""seed targeted-practice config (tunable thresholds & mix ratios)

Revision ID: b2f3c4d5e6a7
Revises: 08ad9636c3f1
Create Date: 2026-06-29 03:30:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2f3c4d5e6a7"
down_revision: Union[str, None] = "08ad9636c3f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KEYS = [
    "practice_promote_ss",
    "practice_demote_ss",
    "practice_promote_streak",
    "practice_warmup_ratio",
    "practice_stretch_ratio",
    "targeted_batch_size",
]


def upgrade() -> None:
    # Tunable parameters for the adaptive targeted-practice engine. Editable via
    # PUT /v1/admin/config/{key} so SLPs can adjust them without a deploy.
    op.execute(
        sa.text("""
        INSERT INTO app_config
            (guid, key, value, value_type, description, is_editable, created_at, last_modified_at)
        VALUES
            (gen_random_uuid(), 'practice_promote_ss',     '3',   'float',
             'Max %SS for an attempt to count as clean (advances mastery)',      true, now(), now()),
            (gen_random_uuid(), 'practice_demote_ss',      '8',   'float',
             '%SS at/above which a sound''s difficulty is dropped',              true, now(), now()),
            (gen_random_uuid(), 'practice_promote_streak', '3',   'int',
             'Consecutive clean attempts needed to advance a difficulty level',  true, now(), now()),
            (gen_random_uuid(), 'practice_warmup_ratio',   '0.2', 'float',
             'Fraction of a practice batch served one tier easier (warm-up)',    true, now(), now()),
            (gen_random_uuid(), 'practice_stretch_ratio',  '0.2', 'float',
             'Fraction of a practice batch served one tier harder (stretch)',    true, now(), now()),
            (gen_random_uuid(), 'targeted_batch_size',     '10',  'int',
             'Default number of phrases in a targeted practice batch',           true, now(), now())
        """)
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM app_config WHERE key IN :keys").bindparams(
            sa.bindparam("keys", _KEYS, expanding=True)
        )
    )
