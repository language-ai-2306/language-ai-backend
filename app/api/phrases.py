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
from app.services import phrase as phrase_service
from app.services.game import record_deliveries, select_unseen_phrases

# ---------------------------------------------------------------------------
# Content management: /phrases
# ---------------------------------------------------------------------------
router = APIRouter(prefix="/phrases", tags=["phrases"])


@router.post("", response_model=PhraseRead, status_code=status.HTTP_201_CREATED)
def create_phrase(
    payload: PhraseCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.DOCTOR)),
) -> DisfluencyPhrase:
    return phrase_service.create_phrase(db, payload)


@router.get("", response_model=List[PhraseRead])
def list_phrases(
    difficulty: Optional[Difficulty] = None,
    ailment_type_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> List[DisfluencyPhrase]:
    return phrase_service.list_phrases(db, difficulty, ailment_type_id, skip, limit)


@router.get("/{phrase_id}", response_model=PhraseRead)
def get_phrase(
    phrase_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> DisfluencyPhrase:
    return phrase_service.get_or_404(db, phrase_id)


@router.patch("/{phrase_id}", response_model=PhraseRead)
def update_phrase(
    phrase_id: int,
    payload: PhraseUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.DOCTOR)),
) -> DisfluencyPhrase:
    return phrase_service.update_phrase(db, phrase_id, payload)


@router.delete("/{phrase_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_phrase(
    phrase_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.DOCTOR)),
) -> None:
    phrase_service.delete_phrase(db, phrase_id)


# ---------------------------------------------------------------------------
# Patient-facing game query: /game/phrases
# ---------------------------------------------------------------------------
game_router = APIRouter(prefix="/game", tags=["game"])


@game_router.get("/phrases", response_model=List[PhraseRead])
def get_game_phrases(
    difficulty: Difficulty = Query(..., description="Which difficulty to play"),
    count: int = Query(10, ge=1, le=50, description="How many phrases to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.PATIENT)),
) -> List[DisfluencyPhrase]:
    phrases = select_unseen_phrases(db, user_id=current_user.id, count=count, difficulty=difficulty)
    record_deliveries(db, current_user.id, phrases, DeliveryContext.GAME)
    db.commit()
    return phrases
