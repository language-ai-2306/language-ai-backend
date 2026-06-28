"""
PracticeAttempt — one row per "Repeat After Me" attempt.

Every time a patient records themselves repeating a practice phrase and the
audio is analysed, the full disfluency breakdown is stored here. This is the
source of truth the speech-therapist dashboard reads from to show a patient's
progress, their hardest words/sounds, and their dominant stutter type over time.

The most dashboard-relevant scalar metrics (fluency, coverage, dominant
disfluency, retry flag) are promoted to their own columns so they can be
filtered/sorted/averaged in SQL cheaply; the full, richer payloads
(every disfluency event, the recognition detail, the complete score set) are
kept verbatim in JSONB columns.
"""

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import AbstractEntity


class PracticeAttempt(AbstractEntity):
    __tablename__ = "practice_attempt"

    # Who made the attempt.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Which phrase was being practiced. Nullable so a free-text / demo analysis
    # (no catalogued phrase) can still be stored; SET NULL keeps the attempt if
    # the phrase is later deleted.
    phrase_id: Mapped[int | None] = mapped_column(
        ForeignKey("disfluency_phrase.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # The target text the patient was asked to say, and what they actually said.
    reference_phrase: Mapped[str] = mapped_column(Text, nullable=False)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Where the recording lives (S3), if it was uploaded. Lets a therapist
    # replay the attempt from the dashboard.
    audio_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Promoted scalar metrics (cheap to query for the dashboard) ───────────
    fluency_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    coverage_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    stutter_frequency_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    words_per_minute: Mapped[float | None] = mapped_column(Float, nullable=True)
    dominant_disfluency: Mapped[str | None] = mapped_column(String(50), nullable=True)
    should_retry: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    child_age: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Full payloads, kept verbatim ─────────────────────────────────────────
    disfluencies: Mapped[list | None] = mapped_column(JSONB, nullable=True)   # every event
    recognition: Mapped[dict | None] = mapped_column(JSONB, nullable=True)    # stress words/sounds, impact
    scores: Mapped[dict | None] = mapped_column(JSONB, nullable=True)         # complete score set

    user: Mapped["User"] = relationship()  # noqa: F821
    phrase: Mapped["DisfluencyPhrase | None"] = relationship()  # noqa: F821
