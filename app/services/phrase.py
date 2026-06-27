"""Phrase service — disfluency phrase CRUD business logic."""

from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.disfluency import Difficulty, DisfluencyPhrase
from app.schemas.phrase import PhraseCreate, PhraseUpdate


def get_or_404(db: Session, phrase_id: int) -> DisfluencyPhrase:
    phrase = db.get(DisfluencyPhrase, phrase_id)
    if phrase is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Phrase not found")
    return phrase


def create_phrase(db: Session, payload: PhraseCreate) -> DisfluencyPhrase:
    phrase = DisfluencyPhrase(
        sentence=payload.sentence,
        ailment_type_id=payload.ailment_type_id,
        difficulty=payload.difficulty,
    )
    db.add(phrase)
    db.commit()
    db.refresh(phrase)
    return phrase


def list_phrases(
    db: Session,
    difficulty: Optional[Difficulty],
    ailment_type_id: Optional[int],
    skip: int,
    limit: int,
) -> List[DisfluencyPhrase]:
    query = select(DisfluencyPhrase)
    if difficulty is not None:
        query = query.where(DisfluencyPhrase.difficulty == difficulty)
    if ailment_type_id is not None:
        query = query.where(DisfluencyPhrase.ailment_type_id == ailment_type_id)
    return list(db.scalars(query.offset(skip).limit(limit)).all())


def update_phrase(db: Session, phrase_id: int, payload: PhraseUpdate) -> DisfluencyPhrase:
    phrase = get_or_404(db, phrase_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(phrase, field, value)
    db.commit()
    db.refresh(phrase)
    return phrase


def delete_phrase(db: Session, phrase_id: int) -> None:
    phrase = get_or_404(db, phrase_id)
    db.delete(phrase)
    db.commit()
