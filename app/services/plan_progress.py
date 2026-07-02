"""Plan progress — record a plan-linked attempt and run the advancement engine.

Called from the exercise `/attempt` endpoint when a `plan_item_id` is supplied.
Advancement mirrors the Lidcombe/GILCU gate: advance one rung when the fluency
score holds above a threshold over the last `window` attempts.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.disfluency import Difficulty
from app.models.practice_plan import (
    PlanItem,
    PlanItemAttempt,
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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def record_attempt(db: Session, user: User, plan_item_id, result: dict[str, Any]) -> PlanItemAttempt:
    """Log a plan-linked attempt and (if AUTO) evaluate advancement.

    `plan_item_id` is the item's GUID. Verifies the item belongs to this patient's
    active plan. Raises 404 otherwise.
    """
    item = get_by_guid(db, PlanItem, plan_item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan item not found")
    plan = db.get(PracticePlan, item.plan_id)
    # plan.patient_id is the patient's user.id — must match the caller.
    if plan is None or plan.patient_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan item not found")

    score = (result.get("scores") or {}).get("fluency_score")
    attempt = PlanItemAttempt(
        plan_item_id=item.id,
        user_id=user.id,
        fluency_score=score,
        result=result,
        attempted_at=_now(),
    )
    db.add(attempt)
    db.flush()
    _maybe_advance(db, item)
    db.commit()
    db.refresh(attempt)
    return attempt


def _maybe_advance(db: Session, item: PlanItem) -> None:
    adv = item.advancement or {}
    if adv.get("mode", "AUTO") != "AUTO" or item.status != PlanItemStatus.ACTIVE:
        return
    threshold = float(adv.get("threshold", 80))
    window = int(adv.get("window", 3))

    recent = db.scalars(
        select(PlanItemAttempt)
        .where(PlanItemAttempt.plan_item_id == item.id)
        .order_by(PlanItemAttempt.created_at.desc())
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
