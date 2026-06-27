"""
Proficiency test tables.

When a new patient signs up they take a 10-minute, 40-phrase test of mixed
difficulty. We store:

  * ProficiencyTest          -> one row per test attempt (the "session"):
                                who took it, when, the final score, and the
                                starting difficulty we assigned from the result.
  * ProficiencyTestResponse  -> one row per phrase in that test: the patient's
                                result on that specific phrase (full responses).
"""

from typing import List, Optional

from sqlalchemy import Boolean, Float
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import AbstractEntity
from app.models.disfluency import Difficulty


class ProficiencyTest(AbstractEntity):
    __tablename__ = "proficiency_test"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Null while the test is still in progress; set when the patient submits.
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # The starting difficulty we compute from the score. Null until submitted.
    assigned_difficulty: Mapped[Optional[Difficulty]] = mapped_column(
        SAEnum(Difficulty, name="difficulty_enum", create_type=False),
        nullable=True,
    )

    # True once the patient has submitted answers.
    is_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    responses: Mapped[List["ProficiencyTestResponse"]] = relationship(
        back_populates="test",
        cascade="all, delete-orphan",
    )


class ProficiencyTestResponse(AbstractEntity):
    __tablename__ = "proficiency_test_response"

    test_id: Mapped[int] = mapped_column(
        ForeignKey("proficiency_test.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    phrase_id: Mapped[int] = mapped_column(
        ForeignKey("disfluency_phrase.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Per-phrase result. score is a 0.0–1.0 quality from your audio analysis;
    # is_correct is a simple pass/fail you can derive from a threshold.
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_correct: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    test: Mapped["ProficiencyTest"] = relationship(back_populates="responses")
