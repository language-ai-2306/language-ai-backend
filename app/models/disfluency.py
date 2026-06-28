"""
DisfluencyPhrase — a practice sentence a patient reads aloud.

`difficulty` is an ENUM: the value must be one of a fixed set (EASY / MEDIUM /
HARD). We define it as a Python `Enum`; SQLAlchemy turns it into a real
PostgreSQL ENUM type so the database itself rejects any other value.
"""

import enum

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import AbstractEntity


class Difficulty(str, enum.Enum):
    EASY = "EASY"
    MEDIUM = "MEDIUM"
    HARD = "HARD"
    TONGUE_TWISTER = "TONGUE_TWISTER"


class DisfluencyPhrase(AbstractEntity):
    __tablename__ = "disfluency_phrase"

    # `Text` (vs String(n)) = unbounded length, good for full sentences.
    sentence: Mapped[str] = mapped_column(Text, nullable=False)

    ailment_type_id: Mapped[int] = mapped_column(
        ForeignKey("ailment_type.id", ondelete="CASCADE"),
        nullable=False,
    )

    target_phoneme: Mapped[str | None] = mapped_column(String(10), nullable=True)

    difficulty: Mapped[Difficulty] = mapped_column(
        SAEnum(Difficulty, name="difficulty_enum"),
        nullable=False,
        default=Difficulty.EASY,
    )

    ailment_type: Mapped["AilmentType"] = relationship()  # noqa: F821 (resolved at runtime)
