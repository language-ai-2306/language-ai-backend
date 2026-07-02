"""Schemas for the SLP (doctor) dashboard — read-only analytics over the data the
app already stores (attempts, sessions, plans, disfluency profile).

All ids are GUIDs.
"""

import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# --- Tier 1: caseload overview ------------------------------------------------
class CaseloadPatient(BaseModel):
    patient_id: uuid.UUID
    name: str
    email: Optional[str] = None
    age: Optional[int] = None
    last_active_at: Optional[datetime] = None
    adherence_pct: Optional[int] = None          # completed vs scheduled, this week
    current_ss: Optional[float] = None           # recent avg %SS
    ss_trend: Optional[str] = None               # improving | worsening | flat
    dominant_disfluency: Optional[str] = None
    alerts: List[str] = Field(default_factory=list)  # regression | plateau | low_adherence | inactive


class CaseloadResponse(BaseModel):
    patients: List[CaseloadPatient] = Field(default_factory=list)


# --- Tier 2: patient detail ---------------------------------------------------
class MetricDelta(BaseModel):
    value: Optional[float] = None
    vs_last_week: Optional[float] = None
    vs_baseline: Optional[float] = None


class TrendPoint(BaseModel):
    week_start: date
    avg_fluency: Optional[float] = None
    avg_ss: Optional[float] = None
    attempts: int


class ContextStat(BaseModel):
    exercise_type: str
    attempts: int
    avg_fluency: Optional[float] = None
    avg_ss: Optional[float] = None


class SoundStat(BaseModel):
    target_phoneme: str
    current_difficulty: Optional[str] = None
    mastery_level: Optional[str] = None
    rolling_ss: Optional[float] = None
    attempts: int


class AdherenceDay(BaseModel):
    date: date
    completed: int


class PatientDetailResponse(BaseModel):
    patient_id: uuid.UUID
    name: str
    age: Optional[int] = None
    dominant_disfluency: Optional[str] = None
    active_plans: List[str] = Field(default_factory=list)
    # Headline metrics (each with deltas).
    fluency: MetricDelta
    stutter_frequency: MetricDelta
    words_per_minute: MetricDelta
    # Charts.
    fluency_trend: List[TrendPoint] = Field(default_factory=list)
    disfluency_breakdown: Dict[str, int] = Field(default_factory=dict)
    context_comparison: List[ContextStat] = Field(default_factory=list)
    per_sound: List[SoundStat] = Field(default_factory=list)
    # Adherence.
    adherence_this_week: Dict[str, Any] = Field(default_factory=dict)  # scheduled / completed / pct
    practice_calendar: List[AdherenceDay] = Field(default_factory=list)  # last 28 days


# --- Tier 3: attempt drill-down -----------------------------------------------
class AttemptListItem(BaseModel):
    attempt_id: uuid.UUID
    created_at: datetime
    exercise_type: Optional[str] = None
    fluency_score: Optional[float] = None
    stutter_frequency_percent: Optional[float] = None
    words_per_minute: Optional[float] = None
    dominant_disfluency: Optional[str] = None


class AttemptListResponse(BaseModel):
    attempts: List[AttemptListItem] = Field(default_factory=list)
    total: int = 0


class AttemptDetail(BaseModel):
    attempt_id: uuid.UUID
    created_at: datetime
    exercise_type: Optional[str] = None
    reference_phrase: Optional[str] = None
    transcript: Optional[str] = None
    audio_url: Optional[str] = None
    fluency_score: Optional[float] = None
    coverage_score: Optional[float] = None
    stutter_frequency_percent: Optional[float] = None
    words_per_minute: Optional[float] = None
    dominant_disfluency: Optional[str] = None
    disfluencies: Optional[list] = None
    recognition: Optional[dict] = None
    scores: Optional[dict] = None
