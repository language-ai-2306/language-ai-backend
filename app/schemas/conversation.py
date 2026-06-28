from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class StartSessionResponse(BaseModel):
    session_id: UUID
    turn_number: int          # always 1 — Ollie's opening turn
    text: str                 # Ollie's greeting + first question
    audio: str                # MP3 of the greeting (audio/mpeg), base64-encoded, played client-side


class DisfluencyEventOut(BaseModel):
    type: str
    word: str | None = None
    timestamp_start: float | None = None
    timestamp_end: float | None = None
    severity: str | None = None


class TurnResponse(BaseModel):
    turn_id: int
    session_id: UUID
    turn_number: int
    child_transcript: str
    child_audio_url: str
    text: str
    audio: str                # MP3 of Ollie's reply (audio/mpeg), base64-encoded, played client-side
    disfluency_count: int
    disfluencies: list[DisfluencyEventOut]


class TurnSummary(BaseModel):
    turn_number: int
    child_transcript: str | None
    ai_text: str | None
    child_audio_url: str | None
    disfluency_count: int
    disfluencies: list[DisfluencyEventOut]


class SessionReportResponse(BaseModel):
    session_id: UUID
    total_turns: int
    turns: list[TurnSummary]


# ── Session listing (patient's own history) ───────────────────────────────────

class SessionSummary(BaseModel):
    """One row in the patient's session list — aggregate stats, no turn detail."""
    session_id: UUID
    started_at: datetime
    last_active_at: datetime
    total_turns: int
    total_disfluencies: int
    disfluency_rate: float  # disfluencies per turn


class SessionListResponse(BaseModel):
    sessions: list[SessionSummary]
    total: int


# ── Session end ───────────────────────────────────────────────────────────────

class SessionEndResponse(BaseModel):
    """Returned when a patient explicitly ends a session."""
    session_id: UUID
    total_turns: int
    total_disfluencies: int
    disfluency_breakdown: dict[str, int]  # {"repetition": 3, "block": 1, ...}
    started_at: datetime
    ended_at: datetime


# ── Doctor progress view ──────────────────────────────────────────────────────

class ProgressPoint(BaseModel):
    """One session in a patient's disfluency trend."""
    session_id: UUID
    date: datetime
    total_turns: int
    total_disfluencies: int
    disfluencies_per_turn: float
    by_type: dict[str, int]


class PatientProgressResponse(BaseModel):
    user_id: int
    sessions_analysed: int
    trend: list[ProgressPoint]  # oldest first
