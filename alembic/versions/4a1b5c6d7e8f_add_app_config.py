"""add app_config table

Revision ID: 4a1b5c6d7e8f
Revises: 3c2e068d5a8e
Create Date: 2026-06-28 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "4a1b5c6d7e8f"
down_revision: Union[str, None] = "3c2e068d5a8e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_config",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "guid",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_modified_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("value_type", sa.String(10), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_editable", sa.Boolean(), nullable=False, server_default="true"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guid"),
    )
    op.create_index("ix_app_config_guid", "app_config", ["guid"], unique=True)
    op.create_index("ix_app_config_key", "app_config", ["key"], unique=True)

    # Seed the initial business rules.
    # Values can be changed via PUT /v1/admin/config/{key} without a deploy.
    op.execute(
        sa.text("""
        INSERT INTO app_config
            (guid, key, value, value_type, description, is_editable, created_at, last_modified_at)
        VALUES
            (gen_random_uuid(), 'phrase_repeat_block_days',      '15', 'int',
             'Days before the same phrase can be served to a patient again', true, now(), now()),
            (gen_random_uuid(), 'proficiency_test_phrase_count', '40', 'int',
             'Number of phrases included in the proficiency assessment',     true, now(), now()),
            (gen_random_uuid(), 'game_batch_size',               '10', 'int',
             'How many phrases are returned in a single game batch',         true, now(), now()),
            (gen_random_uuid(), 'max_conversation_turns',        '20',  'int',
             'Maximum turns allowed per AI conversation session',                    true, now(), now()),
            (gen_random_uuid(), 'ai_max_response_tokens',       '150', 'int',
             'Maximum tokens the AI character may use in a single reply',            true, now(), now()),
            (gen_random_uuid(), 'ai_character_name',            'Ollie', 'str',
             'Display name of the AI companion character shown to children',         true, now(), now()),
            (gen_random_uuid(), 'ai_character_description',
             'a warm, fun-loving children''s author who adores hearing kids tell stories about their lives', 'str',
             'One-line personality description injected into the AI system prompt',  true, now(), now())
        """)
    )


def downgrade() -> None:
    op.drop_index("ix_app_config_key", table_name="app_config")
    op.drop_index("ix_app_config_guid", table_name="app_config")
    op.drop_table("app_config")
