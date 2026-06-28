"""PracticeSkill — a child's adaptive mastery state for one target sound.

One row per (user, target_phoneme). Updated after every Repeat-After-Me attempt
on that sound: it tracks a recency-weighted %SS (percent syllables stuttered),
the child's current working difficulty for that sound, and a mastery label. The
phrase selector reads this to serve the right difficulty per sound and to decide
when to promote/demote.

Difficulty and mastery are plain strings (not DB enums) to avoid Postgres enum
coupling and to keep ingestion robust.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import AbstractEntity


class PracticeSkill(AbstractEntity):
    __tablename__ = "practice_skill"
    __table_args__ = (
        UniqueConstraint("user_id", "target_phoneme", name="uq_practice_skill_user_phoneme"),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_phoneme: Mapped[str] = mapped_column(String(16), nullable=False)

    # Current working difficulty for this sound: EASY / MEDIUM / HARD / TONGUE_TWISTER.
    current_difficulty: Mapped[str] = mapped_column(String(20), nullable=False, default="EASY")

    # Mastery label: struggling / practicing / mastered.
    mastery_level: Mapped[str] = mapped_column(String(16), nullable=False, default="practicing")

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Recency-weighted %SS (exponential moving average); lower is better.
    rolling_ss: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Consecutive attempts at/under the promotion threshold (drives level-up).
    consecutive_low: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    last_practiced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship()  # noqa: F821
