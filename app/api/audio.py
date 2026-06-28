"""Audio analysis routes.

  * GET  /v1/audio/defaults  — sample inputs for the stateless analyser.
  * POST /v1/audio/analyze   — stateless analysis (no auth, no DB). Handy for
                               demos and quick manual testing.
  * GET  /v1/audio/patients/{id}/practice-skill — doctor mastery matrix.

The patient-facing Repeat-After-Me endpoints (next-phrase, attempt) live in
app.api.repeat_after_me and reuse `_analyse_recording` from here.

    curl -s -X POST http://127.0.0.1:8000/v1/audio/analyze \
      -F 'audio=@recording.wav' \
      -F 'reference_phrase=I see a snake' \
      -F 'child_age=8' | python3 -m json.tool

Requires the ML (transcription) service running, or pass use_mock=true.
"""

import logging
import os
import tempfile
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.analysis import pipeline
from app.analysis.audio_utils import preprocess_audio, validate_audio
from app.analysis.text_utils import normalise_text
from app.config.settings import settings
from app.core.deps import require_role
from app.db.base import get_db
from app.models.user import User, UserRole
from app.services import practice_planner
from app.schemas.practice import PracticeSkillResponse
from app.services.ml_client import MLServiceError, ml_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/audio", tags=["audio"])

DEFAULT_REFERENCE_PHRASE = "sometimes I find it hard to say what I mean"
DEFAULT_CHILD_AGE = 8


async def _analyse_recording(
    content: bytes,
    filename: str | None,
    reference_phrase: str,
    child_age: int,
    use_mock: bool,
) -> tuple[dict[str, Any], bytes]:
    """Preprocess, transcribe and analyse an uploaded recording.

    Returns the analysis result dict plus the preprocessed WAV bytes (so the
    caller can upload the recording to S3 if it wants to persist it).
    Raises HTTPException(400) on bad audio and HTTPException(502) if the ML
    transcription service is unavailable.
    """
    if not content:
        raise HTTPException(status_code=400, detail="Audio file is empty")

    suffix = os.path.splitext(filename or "audio.wav")[1] or ".wav"

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

        if use_mock:
            transcription = ml_client.mock_transcribe(reference_phrase)
        else:
            try:
                transcription = await ml_client.transcribe(
                    wav_bytes, filename="processed.wav", content_type="audio/wav"
                )
            except MLServiceError as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"{exc} Start the ML service on 8081, or pass use_mock=true.",
                ) from exc

        result = pipeline.analyze(
            wav_path,
            transcription["transcript"],
            transcription["words"],
            reference_phrase,
            child_age,
        )

    result["reference_phrase"] = normalise_text(reference_phrase)
    return result, wav_bytes


@router.get("/defaults")
async def get_defaults() -> dict[str, Any]:
    return {
        "note": "No database required. Point ML_SERVICE_URL at your language-ai-ml (transcription) service.",
        "ml_service_url": settings.ml_service_url,
        "reference_phrase": DEFAULT_REFERENCE_PHRASE,
        "child_age": DEFAULT_CHILD_AGE,
        "endpoint": "POST /v1/audio/analyze (multipart: audio, reference_phrase, child_age, use_mock)",
    }


@router.post("/analyze", summary="Analyse a recording (stateless, no DB)")
async def analyze_upload(
    audio: UploadFile = File(...),
    reference_phrase: str = Form(default=DEFAULT_REFERENCE_PHRASE),
    child_age: int = Form(default=DEFAULT_CHILD_AGE, ge=5, le=15),
    use_mock: bool = Form(default=False),
) -> dict[str, Any]:
    """Run the full disfluency analysis and return it. Nothing is stored."""
    content = await audio.read()
    result, _ = await _analyse_recording(
        content, audio.filename, reference_phrase, child_age, use_mock
    )
    return result


@router.get(
    "/patients/{user_id}/practice-skill",
    response_model=PracticeSkillResponse,
    summary="Get a patient's per-sound practice mastery matrix",
    responses={403: {"description": "Doctor role required"}},
)
def get_practice_skill(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.DOCTOR)),
) -> PracticeSkillResponse:
    """
    The patient's adaptive mastery state, one row per practised sound (worst
    first): current difficulty, mastery level, attempts, and recency-weighted %SS.
    """
    return PracticeSkillResponse(**practice_planner.get_practice_skill(db, user_id))
