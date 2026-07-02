"""Plan progress — resolve a plan-linked attempt and run the advancement engine.

Called from the exercise `/attempt` endpoint when a `plan_item_id` is supplied.
The attempt itself is stored as a `practice_attempt` row (carrying `plan_item_id`);
this module only resolves/authorises the item and, after the attempt is stored,
evaluates advancement over that item's `practice_attempt` history.

Advancement mirrors the Lidcombe/GILCU gate: advance one rung when the fluency
score holds above a threshold over the last `window` attempts.
"""

import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.disfluency import Difficulty
from app.models.practice_attempt import PracticeAttempt
from app.models.practice_plan import (
    PlanItem,
    PlanItemSession,
    PlanItemSessionStatus,
    PlanItemStatus,
    PracticePlan,
)
from app.models.user import User
from app.core.guid import get_by_guid

logger = logging.getLogger(__name__)

# Difficulty ladder per game (open games have no TONGUE_TWISTER; Ollie has none).
_LADDERS = {
    "REPEAT_AFTER_ME": ["EASY", "MEDIUM", "HARD", "TONGUE_TWISTER"],
    "READ_IT_LOUD": ["EASY", "MEDIUM", "HARD", "TONGUE_TWISTER"],
    "STORY_TELLER": ["EASY", "MEDIUM", "HARD"],
    "PICTURE_TALK": ["EASY", "MEDIUM", "HARD"],
    "TALK_WITH_OLLIE": [],
}


def resolve_owned_item(db: Session, user: User, plan_item_id) -> PlanItem:
    """Resolve a plan item by GUID and verify it belongs to this patient's plan.

    `plan_item_id` is the item's GUID. Raises 404 if unknown or not the caller's.
    Used by the exercise `/attempt` flow to stamp the attempt's `plan_item_id`.
    """
    item = get_by_guid(db, PlanItem, plan_item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan item not found")
    plan = db.get(PracticePlan, item.plan_id)
    # plan.patient_id is the patient's user.id — must match the caller.
    if plan is None or plan.patient_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan item not found")
    return item


def open_session(db: Session, user: User, item: PlanItem) -> PlanItemSession:
    """Find-or-create today's session (occurrence) for this plan item.

    One session per item per calendar day: the first attempt of the day creates it,
    later reps that day reuse it. Attempts link to the returned session.
    """
    today = datetime.now(timezone.utc).date()
    session = db.scalar(
        select(PlanItemSession).where(
            PlanItemSession.plan_item_id == item.id,
            PlanItemSession.occurrence_date == today,
        )
    )
    if session is None:
        session = PlanItemSession(
            plan_item_id=item.id,
            user_id=user.id,
            occurrence_date=today,
            status=PlanItemSessionStatus.IN_PROGRESS,
            attempts_count=0,
        )
        db.add(session)
        db.commit()
        db.refresh(session)
    return session


def finalize_session_and_advance(db: Session, item: PlanItem, session: PlanItemSession | None) -> None:
    """Call AFTER the attempt is persisted: refresh the session's rep tally, then
    evaluate item advancement. Commits.

    The session's status is NOT changed here — it stays IN_PROGRESS until the
    frontend explicitly ends the session (see `complete_session` / the /end route).
    """
    if session is not None:
        count = db.scalar(
            select(func.count(PracticeAttempt.id)).where(
                PracticeAttempt.plan_item_session_id == session.id
            )
        ) or 0
        session.attempts_count = int(count)
        db.commit()
    _maybe_advance(db, item)
    db.commit()


def complete_session(db: Session, user: User, item: PlanItem) -> PlanItemSession:
    """Mark today's session COMPLETED — the child finished the exercise for this
    calendar day. Find-or-create then complete, so /end works even if /start was
    skipped. Idempotent (completing an already-complete session is a no-op)."""
    session = open_session(db, user, item)
    session.status = PlanItemSessionStatus.COMPLETED
    db.commit()
    db.refresh(session)
    return session


def _maybe_advance(db: Session, item: PlanItem) -> None:
    adv = item.advancement or {}
    if adv.get("mode", "AUTO") != "AUTO" or item.status != PlanItemStatus.ACTIVE:
        return
    threshold = float(adv.get("threshold", 80))
    window = int(adv.get("window", 3))

    recent = db.scalars(
        select(PracticeAttempt)
        .join(PlanItemSession, PracticeAttempt.plan_item_session_id == PlanItemSession.id)
        .where(PlanItemSession.plan_item_id == item.id)
        .order_by(PracticeAttempt.created_at.desc())
        .limit(window)
    ).all()
    if len(recent) < window or not all((a.fluency_score or 0) >= threshold for a in recent):
        return

    ladder = _LADDERS.get(item.exercise_type, [])
    if item.difficulty is not None and item.difficulty.value in ladder:
        idx = ladder.index(item.difficulty.value)
        if idx + 1 < len(ladder):
            item.difficulty = Difficulty(ladder[idx + 1])  # bump one rung
            logger.info("plan_item %s advanced to %s", item.id, item.difficulty.value)
            return

    # Top rung (or no difficulty ladder) → complete this item, unlock the next locked one.
    item.status = PlanItemStatus.COMPLETED
    logger.info("plan_item %s completed", item.id)
    nxt = db.scalars(
        select(PlanItem)
        .where(PlanItem.plan_id == item.plan_id, PlanItem.status == PlanItemStatus.LOCKED)
        .order_by(PlanItem.sequence)
        .limit(1)
    ).first()
    if nxt is not None:
        nxt.status = PlanItemStatus.ACTIVE
        logger.info("plan_item %s unlocked", nxt.id)
