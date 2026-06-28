"""Audio analysis routes — the "Repeat After Me" feature.

Two entry points:

  * POST /v1/audio/analyze   — stateless analysis (no auth, no DB). Handy for
                               demos and quick manual testing.
  * POST /v1/audio/attempts  — patient-facing: analyse a recording of a practice
                               phrase AND persist the result (linked to the
                               patient and, when given, the catalogued phrase).
                               This is what feeds the speech-therapist dashboard.

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
from app.models.disfluency import DisfluencyPhrase
from app.models.user import User, UserRole
from app.services import practice as practice_service
from app.services import practice_planner
from app.services import storage
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


@router.post(
    "/attempts",
    status_code=201,
    summary="Analyse a practice attempt and store the result",
    responses={
        403: {"description": "Patient role required"},
        404: {"description": "phrase_id given but no such phrase"},
    },
)
async def submit_attempt(
    audio: UploadFile = File(..., description="The patient's recording (WAV/M4A)"),
    phrase_id: int | None = Form(
        default=None,
        description="ID of the catalogued phrase being practiced. If given, its "
        "text is used as the target and the attempt is linked to it.",
    ),
    reference_phrase: str | None = Form(
        default=None,
        description="Target text — used only when phrase_id is not supplied.",
    ),
    child_age: int = Form(default=DEFAULT_CHILD_AGE, ge=5, le=15),
    use_mock: bool = Form(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.PATIENT)),
) -> dict[str, Any]:
    """
    Patient-facing "Repeat After Me" submission. Analyses the recording, uploads
    it to S3, and persists a PracticeAttempt (linked to the patient and, if
    `phrase_id` is given, the phrase). Returns the analysis plus the stored
    attempt id/guid.
    """
    # Resolve the target text: a catalogued phrase wins over free text.
    phrase: DisfluencyPhrase | None = None
    if phrase_id is not None:
        phrase = db.get(DisfluencyPhrase, phrase_id)
        if phrase is None:
            raise HTTPException(status_code=404, detail="Phrase not found")
        target_text = phrase.sentence
    elif reference_phrase:
        target_text = reference_phrase
    else:
        target_text = DEFAULT_REFERENCE_PHRASE

    content = await audio.read()
    result, wav_bytes = await _analyse_recording(
        content, audio.filename, target_text, child_age, use_mock
    )

    # Upload the recording so a therapist can replay it. Best-effort: a storage
    # hiccup must not lose the analysis itself.
    audio_url: str | None = None
    try:
        audio_url = storage.upload_practice_audio(wav_bytes, current_user.id)
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
    # child's per-sound mastery (promote/demote difficulty). Secondary — never
    # let it break the response.
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
