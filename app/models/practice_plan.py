"""Tailored practice plans — an SLP-authored treatment course for one patient.

Structure:
  * one patient has at most ONE PracticePlan;
  * a plan has many PlanItems (ordered);
  * each PlanItem is ONE game (exercise_type) with its phoneme (drill games only),
    difficulty, schedule (frequency + days + duration), and advancement gate.

Attempts on a plan item are NOT stored here — every attempt (planned or free) is a
`practice_attempt` row; a planned one carries `plan_item_id`. That single table drives
advancement + progress review. Plans REFERENCE content already in `disfluency_phrase`
(exercise_type + difficulty + target_phoneme) — there is no separate plan-content table.
"""

import enum
from datetime import date

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import AbstractEntity
from app.models.disfluency import Difficulty


class PlanStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


class PlanItemStatus(str, enum.Enum):
    LOCKED = "LOCKED"        # not yet unlocked (earlier items must complete first)
    ACTIVE = "ACTIVE"        # currently practisable
    COMPLETED = "COMPLETED"  # advancement criteria met


class PlanItemSessionStatus(str, enum.Enum):
    IN_PROGRESS = "IN_PROGRESS"  # opened; fewer than reps_per_session attempts so far
    COMPLETED = "COMPLETED"      # dosage met (or manually marked done)
    SKIPPED = "SKIPPED"          # occurrence explicitly skipped


class PracticePlan(AbstractEntity):
    __tablename__ = "practice_plan"

    # Both are user.id values (every person reference keys on the `user` table).
    # A patient may have many plans, but only one ACTIVE at a time — enforced by a
    # partial unique index (see migration a0b1c2d3e4f5), not a column-level unique.
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    doctor_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[PlanStatus] = mapped_column(
        SAEnum(PlanStatus, name="plan_status_enum"),
        nullable=False,
        default=PlanStatus.DRAFT,
        index=True,
    )
    start_date: Mapped[date | None] = mapped_column(nullable=True)
    end_date: Mapped[date | None] = mapped_column(nullable=True)

    items: Mapped[list["PlanItem"]] = relationship(
        cascade="all, delete-orphan", order_by="PlanItem.sequence"
    )


class PlanItem(AbstractEntity):
    __tablename__ = "plan_item"

    plan_id: Mapped[int] = mapped_column(
        ForeignKey("practice_plan.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # ONE game per item (matches disfluency_phrase.exercise_type values).
    exercise_type: Mapped[str] = mapped_column(String(20), nullable=False)

    # Phoneme only for REPEAT_AFTER_ME / READ_IT_LOUD; NULL for the open games.
    target_phoneme: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # NULL only for TALK_WITH_OLLIE (which has no difficulty).
    difficulty: Mapped[Difficulty | None] = mapped_column(
        SAEnum(Difficulty, name="difficulty_enum"), nullable=True
    )

    # --- Scheduling: when + how long this game runs ------------------------
    frequency: Mapped[str] = mapped_column(String(10), nullable=False, default="DAILY")  # DAILY/WEEKLY/MONTHLY/CUSTOM
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)          # 5 / 10 / 20 …
    # {"days_of_week": ["MON","WED"], "days_of_month": [1, 15]}
    schedule: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # {"reps_per_session": 1}
    dosage: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # {"mode": "AUTO"|"MANUAL", "metric": "fluency_score", "threshold": 80, "window": 3}
    advancement: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    status: Mapped[PlanItemStatus] = mapped_column(
        SAEnum(PlanItemStatus, name="plan_item_status_enum"),
        nullable=False,
        default=PlanItemStatus.ACTIVE,
    )


class PlanItemSession(AbstractEntity):
    """One scheduled OCCURRENCE of a plan item — e.g. "Monday of week 3".

    A plan item is a single row for the whole (possibly months-long, recurring)
    course; each time its scheduled day comes round the child does a *session*.
    A session groups that day's reps: it is created lazily on the first attempt of
    the day and completes once `reps_per_session` attempts land. This is the entity
    that gives each occurrence its own identity + status, which a bare
    `plan_item_id` on the attempt could not.
    """

    __tablename__ = "plan_item_session"

    plan_item_id: Mapped[int] = mapped_column(
        ForeignKey("plan_item.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The calendar date of this occurrence (one session per item per day).
    occurrence_date: Mapped[date] = mapped_column(nullable=False)
    status: Mapped[PlanItemSessionStatus] = mapped_column(
        SAEnum(PlanItemSessionStatus, name="plan_item_session_status_enum"),
        nullable=False,
        default=PlanItemSessionStatus.IN_PROGRESS,
    )
    attempts_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("plan_item_id", "occurrence_date", name="uq_session_item_date"),
    )
