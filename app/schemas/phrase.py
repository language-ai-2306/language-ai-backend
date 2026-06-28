"""Schemas for disfluency phrases (the practice sentences)."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.disfluency import Difficulty


class PhraseCreate(BaseModel):
    sentence: str = Field(min_length=1)
    ailment_id: int
    difficulty: Difficulty = Difficulty.EASY


class PhraseUpdate(BaseModel):
    sentence: Optional[str] = Field(default=None, min_length=1)
    ailment_id: Optional[int] = None
    difficulty: Optional[Difficulty] = None


class PhraseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    sentence: str
    # The ORM column is `ailment_type_id`; expose it as `ailment_id` in the API.
    ailment_id: int = Field(validation_alias="ailment_type_id")
    difficulty: Difficulty
    target_phoneme: Optional[str] = None
