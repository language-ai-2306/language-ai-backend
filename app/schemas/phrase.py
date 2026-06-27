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
    model_config = ConfigDict(from_attributes=True)

    id: int
    sentence: str
    ailment_id: int
    difficulty: Difficulty
