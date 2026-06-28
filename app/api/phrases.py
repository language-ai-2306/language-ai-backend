"""Phrase routes — thin controller, delegates to PhraseService."""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_role
from app.db.base import get_db
from app.models.delivery import DeliveryContext
from app.models.disfluency import Difficulty, DisfluencyPhrase
from app.models.user import User, UserRole
from app.schemas.phrase import PhraseCreate, PhraseRead, PhraseUpdate
from app.schemas.practice import TargetedPhrasesResponse
from app.services import phrase as phrase_service
from app.services import practice_planner
from app.services.game import record_deliveries, select_unseen_phrases

# ---------------------------------------------------------------------------
# Content management: /phrases
# ---------------------------------------------------------------------------
router = APIRouter(prefix="/phrases", tags=["phrases"])


@router.post(
    "",
    response_model=PhraseRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a practice phrase",
    response_description="The newly created phrase",
    responses={403: {"description": "Doctor role required"}},
)
def create_phrase(
    payload: PhraseCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.DOCTOR)),
) -> DisfluencyPhrase:
    """Create a new practice sentence. Restricted to **doctors** only."""
    return phrase_service.create_phrase(db, payload)


@router.get(
    "",
    response_model=List[PhraseRead],
    summary="List practice phrases",
    response_description="Filtered, paginated list of phrases",
)
def list_phrases(
    difficulty: Optional[Difficulty] = Query(default=None, description="Filter by difficulty: EASY, MEDIUM, HARD"),
    ailment_type_id: Optional[int] = Query(default=None, description="Filter by ailment type ID"),
    skip: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=100, ge=1, le=500, description="Max phrases to return"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> List[DisfluencyPhrase]:
    """List all practice phrases, optionally filtered by difficulty and/or ailment type."""
    return phrase_service.list_phrases(db, difficulty, ailment_type_id, skip, limit)


@router.get(
    "/{phrase_id}",
    response_model=PhraseRead,
    summary="Get a phrase by ID",
    response_description="The requested phrase",
    responses={404: {"description": "Phrase not found"}},
)
def get_phrase(
    phrase_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> DisfluencyPhrase:
    """Fetch a single practice phrase by its ID."""
    return phrase_service.get_or_404(db, phrase_id)


@router.patch(
    "/{phrase_id}",
    response_model=PhraseRead,
    summary="Update a phrase",
    response_description="The updated phrase",
    responses={
        403: {"description": "Doctor role required"},
        404: {"description": "Phrase not found"},
    },
)
def update_phrase(
    phrase_id: int,
    payload: PhraseUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.DOCTOR)),
) -> DisfluencyPhrase:
    """Partially update a practice phrase. Restricted to **doctors** only."""
    return phrase_service.update_phrase(db, phrase_id, payload)


@router.delete(
    "/{phrase_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a phrase",
    responses={
        403: {"description": "Doctor role required"},
        404: {"description": "Phrase not found"},
    },
)
def delete_phrase(
    phrase_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.DOCTOR)),
) -> None:
    """Delete a practice phrase permanently. Restricted to **doctors** only."""
    phrase_service.delete_phrase(db, phrase_id)


# ---------------------------------------------------------------------------
# Patient-facing game query: /game/phrases
# ---------------------------------------------------------------------------
game_router = APIRouter(prefix="/game", tags=["game"])


@game_router.get(
    "/phrases",
    response_model=List[PhraseRead],
    summary="Get game phrases for this session",
    response_description="Randomized batch of unseen phrases at the requested difficulty",
    responses={403: {"description": "Patient role required"}},
)
def get_game_phrases(
    difficulty: Difficulty = Query(..., description="Difficulty level to play: EASY, MEDIUM, HARD"),
    count: int = Query(10, ge=1, le=50, description="How many phrases to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.PATIENT)),
) -> List[DisfluencyPhrase]:
    """
    Return a randomized set of `count` phrases the patient has **not seen in the last 15 days**
    at the given difficulty level. Each phrase returned is immediately recorded as shown,
    so it won't appear again within the 15-day window.
    """
    phrases = select_unseen_phrases(db, user_id=current_user.id, count=count, difficulty=difficulty)
    record_deliveries(db, current_user.id, phrases, DeliveryContext.GAME)
    db.commit()
    return phrases


@game_router.get(
    "/targeted-phrases",
    response_model=TargetedPhrasesResponse,
    summary="Get a personalised, adaptive batch of practice phrases",
    response_description="Phrases aimed at the patient's problem sounds, at their current difficulty",
    responses={403: {"description": "Patient role required"}},
)
def get_targeted_phrases(
    count: int = Query(10, ge=1, le=50, description="How many phrases to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.PATIENT)),
) -> TargetedPhrasesResponse:
    """
    Adaptive 'Repeat After Me' batch. Uses the patient's disfluency profile (from
    conversation **and** past practice) to target their problem sounds, serves each
    sound at the difficulty their mastery has reached, mixes across several sounds,
    and respects the cooldown. New patients (no profile yet) get a balanced warm-up
    set. Each phrase comes with a short reason it was chosen.
    """
    result = practice_planner.build_practice_set(db, current_user.id, count=count)
    return TargetedPhrasesResponse(**result)
