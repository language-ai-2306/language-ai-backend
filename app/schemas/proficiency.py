"""Schemas for the proficiency test flow (start -> submit -> result)."""

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.disfluency import Difficulty
from app.schemas.phrase import PhraseRead


class ProficiencyStartResponse(BaseModel):
    """Returned when a patient starts the test: the test id + the phrases to read."""

    test_id: int
    phrases: List[PhraseRead]


class ProficiencyResponseItem(BaseModel):
    """The patient's result on a single phrase of the test."""

    phrase_id: int
    score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    is_correct: Optional[bool] = None
    # Detected disfluency events for this phrase, if the client analysed the
    # recording. When present they feed the child's unified disfluency profile.
    disfluencies: Optional[List[dict]] = None


class ProficiencySubmit(BaseModel):
    """The full set of answers the patient submits at the end of the test."""

    responses: List[ProficiencyResponseItem]


class ProficiencyResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    test_id: int = Field(validation_alias="id")
    score: Optional[float]
    assigned_difficulty: Optional[Difficulty]
    is_completed: bool
