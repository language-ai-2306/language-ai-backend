"""Repeat-After-Me game routes.

  GET  /v1/repeat-after-me/next-phrase — one phrase at the chosen difficulty,
       personalised to the child's problem sounds, with its AI-voiced audio.
  POST /v1/repeat-after-me/attempt     — analyse the child's recording of a phrase,
       store it, feed the disfluency profile, and update mastery.

The stateless analysis helper and `/v1/audio/analyze` stay in app.api.audio.
"""

import base64
import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.audio import DEFAULT_CHILD_AGE, _analyse_recording
from app.config.settings import settings
from app.core.deps import require_role
from app.db.base import get_db
from app.models.disfluency import Difficulty, DisfluencyPhrase
from app.models.user import User, UserRole
from app.schemas.practice import NextPhraseResponse, StartIntroResponse
from app.services import config_service
from app.services import practice as practice_service
from app.services import practice_planner, storage
from app.services.ml_client import MLServiceError, ml_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/repeat-after-me", tags=["repeat-after-me"])

# Fixed intro spoken at the start of the game. {name} = child, {char} = Ollie.
_INTRO = "Hi {name}! I'm {char}. Let's play Repeat After Me! I'll say a phrase, then it's your turn to say it back."


def _age_from_dob(user: User) -> int:
    """Child's age from their date of birth, clamped to 5–15. Falls back to the
    default when no DOB is set."""
    dob = getattr(user, "dob", None)
    if dob is None:
        return DEFAULT_CHILD_AGE
    today = date.today()
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return max(5, min(15, age))


@router.get(
    "/start",
    response_model=StartIntroResponse,
    summary="Start the game — the AI's spoken introduction (by name)",
    responses={
        403: {"description": "Patient role required"},
        502: {"description": "Voice service unavailable"},
    },
)
async def start(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.PATIENT)),
) -> StartIntroResponse:
    """
    Opens the Repeat-After-Me game with a warm, personalised introduction the AI
    speaks to the child — greeting them by name and explaining how to play —
    returned as text plus the spoken audio (base64 MP3). After this, the client
    shows the four difficulty options and calls /next-phrase.
    """
    name = (getattr(current_user, "first_name", None) or "friend").strip() or "friend"
    character = config_service.get("ai_character_name", db, default=settings.ai_character_name)
    text = _INTRO.format(name=name, char=character)

    try:
        audio_bytes = await ml_client.synthesise(text)
    except MLServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return StartIntroResponse(text=text, audio=base64.b64encode(audio_bytes).decode("ascii"))


@router.get(
    "/next-phrase",
    response_model=NextPhraseResponse,
    summary="Get the next phrase to practise (with AI-voiced audio)",
    response_description="One phrase at the chosen difficulty, plus its spoken audio",
    responses={
        403: {"description": "Patient role required"},
        404: {"description": "No phrases available at that difficulty"},
        502: {"description": "Voice service unavailable"},
    },
)
async def get_next_phrase(
    difficulty: Difficulty = Query(..., description="EASY, MEDIUM, HARD or TONGUE_TWISTER"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.PATIENT)),
) -> NextPhraseResponse:
    """
    The Repeat-After-Me game loop. Returns ONE phrase at the chosen difficulty —
    preferring the child's problem sounds (from their disfluency history) within
    that difficulty — together with the phrase spoken in the AI voice (base64 MP3)
    so the child can hear it before repeating. Submit the child's recording to
    POST /v1/repeat-after-me/attempt with this phrase's id.
    """
    result = practice_planner.next_phrase(db, current_user.id, difficulty)
    if result is None:
        raise HTTPException(status_code=404, detail="No phrases available at that difficulty")

    try:
        audio_bytes = await ml_client.synthesise(result["phrase"].sentence)
    except MLServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return NextPhraseResponse(
        phrase=result["phrase"],
        reason=result["reason"],
        audio=base64.b64encode(audio_bytes).decode("ascii"),
    )


@router.post(
    "/attempt",
    status_code=201,
    summary="Analyse a practice attempt and store the result",
    responses={
        403: {"description": "Patient role required"},
        404: {"description": "phrase_id given but no such phrase"},
        502: {"description": "ML service unavailable"},
    },
)
async def submit_attempt(
    audio: UploadFile = File(..., description="The patient's recording (WAV/M4A)"),
    text: str = Form(..., description="The phrase the child was asked to repeat"),
    use_mock: bool = Form(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.PATIENT)),
) -> dict[str, Any]:
    """
    Patient-facing "Repeat After Me" submission. Analyses the recording of the
    given `text`, uploads it to S3, and persists a PracticeAttempt. The child's
    age is taken from their date of birth. If `text` matches a catalogued phrase,
    the attempt links to it and updates per-sound mastery; either way it feeds the
    disfluency profile. Returns the analysis plus the stored attempt id/guid.
    """
    child_age = _age_from_dob(current_user)

    # Link to a catalogued phrase by its text (enables the per-sound mastery
    # update); free text that matches nothing is still analysed and profiled.
    phrase = db.scalar(select(DisfluencyPhrase).where(DisfluencyPhrase.sentence == text))
    phrase_id = phrase.id if phrase else None

    content = await audio.read()
    result, wav_bytes = await _analyse_recording(
        content, audio.filename, text, child_age, use_mock
    )

    # Upload the recording so a therapist can replay it. Best-effort: a storage
    # hiccup must not lose the analysis itself. Store a presigned (directly
    # openable) link, valid up to 7 days — same pattern as conversation audio.
    audio_url: str | None = None
    try:
        canonical = storage.upload_practice_audio(wav_bytes, current_user.id)
        audio_url = storage.presigned_url(canonical, expires_in=7 * 24 * 3600)
    except Exception:  # noqa: BLE001 - storage is non-critical to persistence
        logger.warning("practice audio upload failed; storing attempt without audio_url")

    attempt = practice_service.record_attempt(
        db,
        user_id=current_user.id,
        reference_phrase=result["reference_phrase"],
        result=result,
        phrase_id=phrase_id,
        child_age=child_age,
        audio_url=audio_url,
    )

    # Feedback loop: feed disfluencies into the unified profile and update the
    # child's per-sound mastery. Secondary — never let it break the response.
    try:
        practice_planner.process_attempt(db, attempt)
    except Exception:  # noqa: BLE001
        logger.warning("practice feedback loop failed for attempt %s", attempt.id, exc_info=True)

    return {
        "attempt_id": attempt.id,
        "attempt_guid": str(attempt.guid),
        "phrase_id": phrase_id,
        "audio_url": audio_url,
        **result,
    }
