"""
Proficiency test routes.

Flow:
  1. POST /proficiency-test/start  -> creates a test, hands back 40 random
     mixed-difficulty phrases the patient hasn't seen in 15 days, and records
     them as shown (so they're excluded from the game for 15 days too).
  2. POST /proficiency-test/{id}/submit -> stores the patient's per-phrase
     results, computes an overall score, and assigns a starting difficulty.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

import uuid

from app.config.settings import settings
from app.core.deps import require_role
from app.core.guid import get_by_guid
from app.services import config_service, disfluency_tracker

logger = logging.getLogger(__name__)
from app.db.base import get_db
from app.models.delivery import DeliveryContext
from app.models.disfluency import Difficulty, DisfluencyPhrase
from app.models.proficiency import ProficiencyTest, ProficiencyTestResponse
from app.models.user import User, UserRole
from app.schemas.proficiency import (
    ProficiencyResult,
    ProficiencyStartResponse,
    ProficiencySubmit,
)
from app.services.game import record_deliveries, select_unseen_phrases

router = APIRouter(prefix="/proficiency-test", tags=["proficiency"])


def _score_to_difficulty(score: float) -> Difficulty:
    """Map a 0.0–1.0 test score to a starting difficulty. Tune these cutoffs."""
    if score >= 0.75:
        return Difficulty.HARD
    if score >= 0.45:
        return Difficulty.MEDIUM
    return Difficulty.EASY


@router.post("/start", response_model=ProficiencyStartResponse, status_code=status.HTTP_201_CREATED)
def start_test(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.PATIENT)),
) -> ProficiencyStartResponse:
    test = ProficiencyTest(user_id=current_user.id, is_completed=False)
    db.add(test)
    db.flush()  # get test.id

    phrase_count = config_service.get_int(
        "proficiency_test_phrase_count", db, default=settings.proficiency_test_phrase_count
    )
    phrases = select_unseen_phrases(
        db,
        user_id=current_user.id,
        count=phrase_count,
    )
    record_deliveries(db, current_user.id, phrases, DeliveryContext.PROFICIENCY_TEST)

    db.commit()
    return ProficiencyStartResponse(test_id=test.guid, phrases=phrases)


@router.post("/{test_id}/submit", response_model=ProficiencyResult)
def submit_test(
    test_id: uuid.UUID,
    payload: ProficiencySubmit,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.PATIENT)),
) -> ProficiencyTest:
    test = get_by_guid(db, ProficiencyTest, test_id)
    if test is None or test.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test not found")
    if test.is_completed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Test already submitted"
        )

    # Store each per-phrase response. The API sends phrase GUIDs; resolve each to
    # its internal id for the FK column (skip unknown phrases).
    for item in payload.responses:
        phrase = get_by_guid(db, DisfluencyPhrase, item.phrase_id)
        if phrase is None:
            continue
        db.add(
            ProficiencyTestResponse(
                test_id=test.id,
                phrase_id=phrase.id,
                score=item.score,
                is_correct=item.is_correct,
            )
        )

    # Compute an overall score: prefer numeric scores; otherwise fraction correct.
    numeric = [r.score for r in payload.responses if r.score is not None]
    if numeric:
        overall = sum(numeric) / len(numeric)
    else:
        flags = [r.is_correct for r in payload.responses if r.is_correct is not None]
        overall = (sum(1 for f in flags if f) / len(flags)) if flags else 0.0

    test.score = overall
    test.assigned_difficulty = _score_to_difficulty(overall)
    test.is_completed = True

    db.commit()
    db.refresh(test)

    # Feed any per-phrase disfluencies into the unified profile (source="proficiency").
    # Secondary to returning the result — never let it break the response.
    events = [d for item in payload.responses for d in (item.disfluencies or [])]
    if events:
        try:
            disfluency_tracker.record_occurrences(
                db, user_id=current_user.id, disfluencies=events, source="proficiency",
            )
        except Exception:  # noqa: BLE001
            logger.warning("failed to record proficiency disfluencies for test %s", test.id, exc_info=True)

    return test
