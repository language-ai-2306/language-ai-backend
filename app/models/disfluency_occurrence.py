"""DisfluencyOccurrence — one row per disfluency detected in a child's speech.

Every disfluency event caught during a conversation turn (and, later, during
Repeat-After-Me practice) is exploded into a row here. Aggregating these rows
gives a per-child "disfluency profile" — which sounds, types and words a child
struggles with most — which in turn drives targeted phrase selection.

The most important column is `sound`: the onset phoneme the child got stuck on.
It joins to `DisfluencyPhrase.target_phoneme`, so a child who blocks on /s/ can
later be served /s/ practice phrases.

Types/severities/source are stored as plain strings (not DB enums) so ingestion
never fails on an unexpected value coming from the ML layer.
"""

from uuid import UUID

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import AbstractEntity


class DisfluencyOccurrence(AbstractEntity):
    __tablename__ = "disfluency_occurrence"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Where it was detected: "conversation" now; "practice"/"proficiency" later.
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="conversation")

    # Origin pointers. session_id mirrors conversation_history (shared UUID, not a
    # FK). turn_id links the exact turn; SET NULL keeps the occurrence if the turn
    # is ever deleted (the profile is analytics — we don't want to lose history).
    session_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    turn_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversation_history.id", ondelete="SET NULL"), nullable=True
    )

    # The disfluency itself.
    disfluency_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    word: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sound: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True)

    timestamp_start: Mapped[float | None] = mapped_column(Float, nullable=True)
    timestamp_end: Mapped[float | None] = mapped_column(Float, nullable=True)

    user: Mapped["User"] = relationship()  # noqa: F821
