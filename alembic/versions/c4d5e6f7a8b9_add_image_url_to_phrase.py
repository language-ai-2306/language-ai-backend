"""add image_url column to disfluency_phrase (Picture Talk)

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-07-02 02:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("disfluency_phrase", sa.Column("image_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("disfluency_phrase", "image_url")
