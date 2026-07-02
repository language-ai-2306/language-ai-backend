"""Schemas for the unified `/v1/exercises/{game}` API."""

import uuid
from typing import Any, List, Optional

from pydantic import BaseModel


class ExerciseIntroResponse(BaseModel):
    """The spoken game introduction (start of a game)."""

    exercise_type: str
    text: str
    audio: Optional[str] = None  # base64 MP3 (Ollie's voice)


class ExerciseContentResponse(BaseModel):
    """One prompt to practise, with optional spoken audio."""

    exercise_type: str
    content_id: str  # phrase id (as a string)
    # The text to show the child: the phrase (RAM), passage (Read It Loud), story
    # (Story Teller), or the describe-prompt question (Picture Talk).
    text: str
    image_url: Optional[str] = None  # Picture Talk only; null for the other games
    reason: Optional[str] = None     # why this prompt was chosen (RAM personalisation)
    audio: Optional[str] = None      # base64 MP3 (spoken text), null when not voiced


class ExerciseAttemptResponse(BaseModel):
    """Result of analysing a recorded attempt."""

    attempt_id: Optional[uuid.UUID] = None  # PracticeAttempt GUID for RAM; None for file-backed games (not persisted)
    exercise_type: str
    content_id: Optional[str] = None         # phrase GUID (as string)
    transcript: Optional[str] = None
    scores: dict[str, Any]
    disfluencies: List[dict[str, Any]]
    should_retry: Optional[bool] = None
    message: Optional[str] = None
    audio_url: Optional[str] = None
