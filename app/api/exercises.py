"""Unified exercise-game API — one surface for every single-shot game.

    GET  /v1/exercises/{game}/start     — spoken intro
    GET  /v1/exercises/{game}/content   — next prompt (+ spoken audio)
    POST /v1/exercises/{game}/attempt   — analyse a recording, score, store

`{game}` ∈ read-it-loud | picture-talk | story-teller | repeat-after-me. Each game
is a strategy in `services/exercise_game`; this router stays identical for all of
them. (Talk with Ollie is a stateful dialogue — it keeps its own /v1/conversation.)
"""

import base64
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Query, UploadFile
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.core.deps import require_role
from app.db.base import get_db
from app.models.disfluency import Difficulty
from app.models.user import User, UserRole
from app.schemas.exercise import (
    ExerciseAttemptResponse,
    ExerciseContentResponse,
    ExerciseIntroResponse,
)
from app.services import config_service
from app.services.exercise_game import get_strategy
from app.services.ml_client import MLServiceError, ml_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/exercises", tags=["exercises"])

_GAME_PATH = Path(..., description="read-it-loud | picture-talk | story-teller | repeat-after-me")


async def _synthesise(text: str) -> str:
    """TTS a line and return base64 MP3, or 502 if the voice service is down."""
    try:
        audio_bytes = await ml_client.synthesise(text)
    except MLServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return base64.b64encode(audio_bytes).decode("ascii")


@router.get(
    "/{game}/start",
    response_model=ExerciseIntroResponse,
    summary="Start a game — the AI's spoken introduction",
    responses={403: {"description": "Patient role required"}, 404: {"description": "Unknown game"},
               502: {"description": "Voice service unavailable"}},
)
async def start(
    game: str = _GAME_PATH,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.PATIENT)),
) -> ExerciseIntroResponse:
    strategy = get_strategy(game)
    name = (getattr(current_user, "first_name", None) or "friend").strip() or "friend"
    character = config_service.get("ai_character_name", db, default=settings.ai_character_name)
    text = strategy.intro(name, character)
    return ExerciseIntroResponse(
        exercise_type=strategy.exercise_type.value, text=text, audio=await _synthesise(text)
    )


@router.get(
    "/{game}/content",
    response_model=ExerciseContentResponse,
    summary="Get the next prompt to practise (with spoken audio)",
    responses={403: {"description": "Patient role required"}, 404: {"description": "Unknown game / no content"},
               502: {"description": "Voice service unavailable"}},
)
async def next_content(
    game: str = _GAME_PATH,
    difficulty: Difficulty = Query(..., description="EASY, MEDIUM, HARD or TONGUE_TWISTER"),
    target_phoneme: str | None = Query(default=None, description="Plan-driven: only serve this onset sound (RAM / Read It Loud)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.PATIENT)),
) -> ExerciseContentResponse:
    strategy = get_strategy(game)
    dto = strategy.next_content(db, current_user, difficulty, target_phoneme)
    if dto is None:
        raise HTTPException(status_code=404, detail="No content available at that difficulty")
    audio = await _synthesise(dto.tts_text) if dto.tts_text else None
    return ExerciseContentResponse(
        exercise_type=dto.exercise_type.value,
        content_id=dto.content_id,
        text=dto.text,
        image_url=dto.image_url,
        reason=dto.reason,
        audio=audio,
    )


@router.post(
    "/{game}/attempt",
    response_model=ExerciseAttemptResponse,
    status_code=201,
    summary="Analyse a recorded attempt, score it, and store it",
    responses={403: {"description": "Patient role required"}, 404: {"description": "Unknown game / content"},
               400: {"description": "Bad audio"}, 502: {"description": "ML service unavailable"}},
)
async def submit_attempt(
    game: str = _GAME_PATH,
    audio: UploadFile = File(..., description="The patient's recording (WAV/M4A)"),
    content_id: str = Form(..., description="The content_id returned by /content"),
    plan_item_id: str | None = Form(default=None, description="Plan item GUID — if practising a plan item, log the attempt to it"),
    use_mock: bool = Form(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.PATIENT)),
) -> ExerciseAttemptResponse:
    strategy = get_strategy(game)
    content = await audio.read()
    result = await strategy.submit(db, current_user, content_id, content, audio.filename, use_mock)

    # If this attempt is part of a plan, log it + run advancement. Never let a plan
    # bookkeeping error swallow the child's scored result.
    if plan_item_id is not None:
        try:
            from app.services import plan_progress
            plan_progress.record_attempt(db, current_user, plan_item_id, result)
        except Exception:  # noqa: BLE001
            logger.warning("plan attempt logging failed for plan_item_id=%s", plan_item_id, exc_info=True)

    return ExerciseAttemptResponse(**result)
