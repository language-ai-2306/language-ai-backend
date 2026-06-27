"""
DisfluencyPhrase — a practice sentence a patient reads aloud.

`difficulty` is an ENUM: the value must be one of a fixed set (EASY / MEDIUM /
HARD). We define it as a Python `Enum`; SQLAlchemy turns it into a real
PostgreSQL ENUM type so the database itself rejects any other value.
"""

import enum

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import AbstractEntity


class Difficulty(str, enum.Enum):
    EASY = "EASY"
    MEDIUM = "MEDIUM"
    HARD = "HARD"


class DisfluencyPhrase(AbstractEntity):
    __tablename__ = "disfluency_phrase"

    # `Text` (vs String(n)) = unbounded length, good for full sentences.
    sentence: Mapped[str] = mapped_column(Text, nullable=False)

    ailment_id: Mapped[int] = mapped_column(
        ForeignKey("ailment.id", ondelete="CASCADE"),
        nullable=False,
    )

    difficulty: Mapped[Difficulty] = mapped_column(
        SAEnum(Difficulty, name="difficulty_enum"),
        nullable=False,
        default=Difficulty.EASY,
    )

    ailment: Mapped["Ailment"] = relationship()  # noqa: F821 (resolved at runtime)
