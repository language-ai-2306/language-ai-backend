"""Conversation AI routes.

POST /v1/conversation/session/start                  — start a new session (generates session id)
POST /v1/conversation/session/{id}/reply             — send child audio, get AI reply
POST /v1/conversation/session/{id}/end               — close a session, get disfluency breakdown
GET  /v1/conversation/session                        — list own sessions (patient)
GET  /v1/conversation/session/{id}                   — full session report (patient owns it OR doctor)
GET  /v1/conversation/patients/{user_id}/progress    — disfluency trend for a patient (doctor only)
"""

import logging
import os
import tempfile
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.analysis.audio_utils import preprocess_audio, validate_audio
from app.core.deps import get_current_user, require_role
from app.db.base import get_db
from app.models.user import User, UserRole
from app.schemas.conversation import (
    DisfluencyProfileResponse,
    PatientProgressResponse,
    SessionEndResponse,
    SessionListResponse,
    SessionReportResponse,
    StartSessionResponse,
    TurnResponse,
)
from app.services import conversation as conv_service
from app.services import disfluency_tracker
from app.services.ml_client import MLServiceError

from fastapi import Depends
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/conversation", tags=["conversation"])


# ── Start session ─────────────────────────────────────────────────────────────

@router.post(
    "/session/start",
    response_model=StartSessionResponse,
    status_code=201,
    summary="Start a new conversation session (Ollie greets first)",
)
async def start_session(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.PATIENT)),
) -> StartSessionResponse:
    """
    Begin a conversation. Ollie opens by greeting the child and asking the first
    question — returned as `ai_text` (with synthesised voice inline as
    `ai_audio_base64`) and stored as turn 1. Pass the returned `session_id` to
    every subsequent /reply call; the child's first reply will be turn 2.
    """
    try:
        result = await conv_service.start_session_with_greeting(db, current_user)
    except MLServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return StartSessionResponse(**result)


# ── Submit a turn ─────────────────────────────────────────────────────────────

@router.post(
    "/session/{session_id}/reply",
    response_model=TurnResponse,
    summary="Submit child audio and get the AI reply",
)
async def submit_reply(
    session_id: uuid.UUID,
    audio: UploadFile = File(..., description="Child's audio recording (WAV or M4A)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.PATIENT)),
) -> TurnResponse:
    """
    Full pipeline per turn:
    1. Preprocess + validate audio
    2. Upload child audio → S3
    3. Transcribe + detect disfluencies via ML service (/v1/analyse)
    4. Enrich with acoustic disfluency detection (local, librosa)
    5. Generate AI reply via Claude
    6. Synthesise AI voice via ML service TTS
    7. Upload AI audio → S3
    8. Persist turn to DB
    """
    content = await audio.read()
    if not content:
        raise HTTPException(status_code=400, detail="Audio file is empty")

    suffix = os.path.splitext(audio.filename or "audio.wav")[1] or ".wav"

    with tempfile.TemporaryDirectory() as tmpdir:
        raw_path = os.path.join(tmpdir, f"raw{suffix}")
        wav_path = os.path.join(tmpdir, "processed.wav")

        with open(raw_path, "wb") as f:
            f.write(content)

        try:
            preprocess_audio(raw_path, wav_path)
            validate_audio(wav_path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        with open(wav_path, "rb") as f:
            wav_bytes = f.read()

        try:
            result = await conv_service.process_turn(
                db=db,
                session_id=session_id,
                user=current_user,
                wav_path=wav_path,
                raw_audio_bytes=wav_bytes,
                original_filename=audio.filename or "audio.wav",
            )
        except MLServiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    return TurnResponse(**result)


# ── End session ───────────────────────────────────────────────────────────────

@router.post(
    "/session/{session_id}/end",
    response_model=SessionEndResponse,
    summary="End a conversation session and get a disfluency breakdown",
)
def end_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.PATIENT)),
) -> SessionEndResponse:
    """
    Closes the session from the patient's perspective and returns a final
    summary with disfluencies broken down by type. No new data is written —
    the summary is computed from the turns already recorded.
    """
    result = conv_service.end_session(db, session_id, current_user.id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Session not found or does not belong to the current user",
        )
    return SessionEndResponse(**result)


# ── List patient's own sessions ───────────────────────────────────────────────

@router.get(
    "/session",
    response_model=SessionListResponse,
    summary="List all sessions for the current patient",
)
def list_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.PATIENT)),
) -> SessionListResponse:
    """Returns a list of the patient's sessions, newest first, with aggregate stats."""
    result = conv_service.list_patient_sessions(db, current_user.id)
    return SessionListResponse(**result)


# ── Session report (patient or doctor) ───────────────────────────────────────

@router.get(
    "/session/{session_id}",
    response_model=SessionReportResponse,
    summary="Get full turn-by-turn session report",
    responses={
        403: {"description": "Patients can only view their own sessions"},
        404: {"description": "Session not found"},
    },
)
def get_session_report(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SessionReportResponse:
    """
    Full transcript + disfluency breakdown, turn by turn.

    - **Doctors** can view any session.
    - **Patients** can only view sessions that belong to them.
    """
    report = conv_service.get_session_report(db, session_id)

    if not report["turns"]:
        raise HTTPException(status_code=404, detail="Session not found")

    if current_user.role == UserRole.PATIENT:
        # Ownership check: verify this session belongs to the requesting patient.
        # The session is owned by whoever submitted its turns. We check by user_id
        # on the first turn fetched inside get_session_report.
        first_turn_user = _get_session_owner(db, session_id)
        if first_turn_user != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to view this session",
            )

    return SessionReportResponse(**report)


# ── Patient progress (doctor only) ───────────────────────────────────────────

@router.get(
    "/patients/{user_id}/progress",
    response_model=PatientProgressResponse,
    summary="Get disfluency trend across all sessions for a patient",
    responses={403: {"description": "Doctor role required"}},
)
def get_patient_progress(
    user_id: int,
    limit: int = 20,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.DOCTOR)),
) -> PatientProgressResponse:
    """
    Returns a list of sessions oldest → newest, each with total disfluencies and
    a breakdown by type. Use `limit` to control how many past sessions to include
    (default 20). Suitable for plotting an improvement chart.
    """
    result = conv_service.get_patient_progress(db, user_id, limit=limit)
    return PatientProgressResponse(**result)


# ── Disfluency profile (doctor only) ─────────────────────────────────────────

@router.get(
    "/patients/{user_id}/disfluency-profile",
    response_model=DisfluencyProfileResponse,
    summary="Get a patient's disfluency profile (top problem sounds / types / words)",
    responses={403: {"description": "Doctor role required"}},
)
def get_patient_disfluency_profile(
    user_id: int,
    window_days: int = 90,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.DOCTOR)),
) -> DisfluencyProfileResponse:
    """
    Aggregates every disfluency caught in the patient's conversations over the
    last `window_days` into a ranked profile: which **sounds**, **types** and
    **words** they struggle with most (severity-weighted). The `by_sound` list
    is what drives targeted Repeat-After-Me phrase selection.
    """
    result = disfluency_tracker.get_disfluency_profile(db, user_id, window_days=window_days)
    return DisfluencyProfileResponse(**result)


# ── Private helper ────────────────────────────────────────────────────────────

def _get_session_owner(db: Session, session_id: uuid.UUID) -> int | None:
    """Return the user_id of whoever owns the session, or None."""
    from app.models.conversation import ConversationHistory
    turn = (
        db.query(ConversationHistory)
        .filter(ConversationHistory.session_id == session_id)
        .first()
    )
    return turn.user_id if turn else None
