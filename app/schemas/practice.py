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
