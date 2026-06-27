"""
Phrase routes.

Two groups, two routers:
  * /phrases       -> content management (create/list/edit/delete the practice
                      sentences). Creating/editing is restricted to doctors.
  * /game/phrases  -> the patient-facing game query: hand the logged-in patient
                      a randomized batch of phrases they haven't seen in 15 days,
                      and record that they were shown.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_role
from app.db.base import get_db
from app.models.delivery import DeliveryContext
from app.models.disfluency import Difficulty, DisfluencyPhrase
from app.models.user import User, UserRole
from app.schemas.phrase import PhraseCreate, PhraseRead, PhraseUpdate
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
    phrase = DisfluencyPhrase(
        sentence=payload.sentence,
        ailment_id=payload.ailment_id,
        difficulty=payload.difficulty,
    )
    db.add(phrase)
    db.commit()
    db.refresh(phrase)
    return phrase


@router.get("", response_model=List[PhraseRead])
def list_phrases(
    difficulty: Optional[Difficulty] = None,
    ailment_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> List[DisfluencyPhrase]:
    query = select(DisfluencyPhrase)
    if difficulty is not None:
        query = query.where(DisfluencyPhrase.difficulty == difficulty)
    if ailment_id is not None:
        query = query.where(DisfluencyPhrase.ailment_id == ailment_id)
    return list(db.scalars(query.offset(skip).limit(limit)).all())


@router.get("/{phrase_id}", response_model=PhraseRead)
def get_phrase(
    phrase_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> DisfluencyPhrase:
    phrase = db.get(DisfluencyPhrase, phrase_id)
    if phrase is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Phrase not found")
    return phrase


@router.patch("/{phrase_id}", response_model=PhraseRead)
def update_phrase(
    phrase_id: int,
    payload: PhraseUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.DOCTOR)),
) -> DisfluencyPhrase:
    phrase = db.get(DisfluencyPhrase, phrase_id)
    if phrase is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Phrase not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(phrase, field, value)
    db.commit()
    db.refresh(phrase)
    return phrase


@router.delete("/{phrase_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_phrase(
    phrase_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.DOCTOR)),
) -> None:
    phrase = db.get(DisfluencyPhrase, phrase_id)
    if phrase is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Phrase not found")
    db.delete(phrase)
    db.commit()


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
    """
    Return a randomized batch of `count` phrases at the given difficulty that
    this patient has NOT seen in the last 15 days, and record them as shown.
    Phrases are NOT filtered by the patient's ailment here — pass that filtering
    in later if you want it; the game query is difficulty-driven per your design.
    """
    phrases = select_unseen_phrases(
        db,
        user_id=current_user.id,
        count=count,
        difficulty=difficulty,
    )
    record_deliveries(db, current_user.id, phrases, DeliveryContext.GAME)
    db.commit()
    return phrases
