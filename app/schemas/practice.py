"""Schemas for Phase 2 targeted practice."""

from datetime import datetime

from pydantic import BaseModel

from app.schemas.phrase import PhraseRead


class TargetedPhraseItem(BaseModel):
    phrase: PhraseRead
    reason: str          # why this phrase was chosen (e.g. "targets 's' at MEDIUM")


class TargetedPhrasesResponse(BaseModel):
    user_id: int
    targeted_sounds: list[str]        # the problem sounds this batch aims at (empty = cold start)
    count: int
    items: list[TargetedPhraseItem]


class NextPhraseResponse(BaseModel):
    """One phrase to practise, at the chosen difficulty, with its spoken audio."""
    phrase: PhraseRead
    reason: str                       # why this phrase (e.g. "targets 'sh' at EASY")
    audio: str                        # base64 MP3 (audio/mpeg) of the phrase in the AI voice


class StartIntroResponse(BaseModel):
    """The AI's spoken introduction to the Repeat-After-Me game, by name."""
    text: str                         # the intro Ollie says (personalised with the child's name)
    audio: str                        # base64 MP3 (audio/mpeg) of the intro in the AI voice


# ── Doctor: per-sound mastery matrix ──────────────────────────────────────────

class SkillRow(BaseModel):
    target_phoneme: str
    current_difficulty: str           # EASY / MEDIUM / HARD / TONGUE_TWISTER
    mastery_level: str                # struggling / practicing / mastered
    attempts: int
    rolling_ss: float | None          # recency-weighted %SS (lower is better)
    last_practiced_at: datetime | None


class PracticeSkillResponse(BaseModel):
    user_id: int
    sounds: list[SkillRow]            # worst (highest %SS) first
