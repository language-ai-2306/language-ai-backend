"""Content selection for the content-driven exercise games — DB-backed.

Prompts for the content games (Read It Loud, Story Teller, Picture Talk) live in
`disfluency_phrase`, tagged by `exercise_type` (+ `difficulty`, `target_phoneme`,
and `image_url` for Picture Talk). This is the single source of truth — the same
table Repeat After Me uses. `content_id` in the API is the phrase id (as a string).
"""

import random
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.disfluency import Difficulty, DisfluencyPhrase
from app.models.exercise import ExerciseType


def select_content(
    db: Session, exercise_type: ExerciseType, difficulty: Difficulty
) -> Optional[DisfluencyPhrase]:
    """Return one random phrase for the game/difficulty, or None if none exist."""
    rows = db.scalars(
        select(DisfluencyPhrase).where(
            DisfluencyPhrase.exercise_type == exercise_type.value,
            DisfluencyPhrase.difficulty == difficulty,
        )
    ).all()
    return random.choice(rows) if rows else None


def get_content(db: Session, content_id: str) -> Optional[DisfluencyPhrase]:
    """Look up a phrase by its id (the content_id passed back from /content)."""
    try:
        phrase_id = int(content_id)
    except (TypeError, ValueError):
        return None
    return db.get(DisfluencyPhrase, phrase_id)
