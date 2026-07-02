"""Audio analysis routes.

  * GET  /v1/audio/defaults  — sample inputs for the stateless analyser.
  * POST /v1/audio/analyze   — stateless analysis (no auth, no DB). Handy for
                               demos and quick manual testing.
  * GET  /v1/audio/patients/{id}/practice-skill — doctor mastery matrix.

The patient-facing games (Repeat After Me, Read It Loud, etc.) live under
app.api.exercises and reuse `_analyse_recording` / `_analyse_free_recording` from here.

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
from app.analysis.feedback import FeedbackGenerator
from app.analysis.free_speech import enrich_with_acoustics
from app.analysis.scorer import Scorer, compute_attempt_flags
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


# Reference-free scoring shares the Scorer/feedback with the pipeline but skips
# coverage (there is no target text for open-ended speech).
_free_scorer = Scorer()
_free_feedback = FeedbackGenerator()


def _free_speech_scores(
    disfluencies: list[dict[str, Any]],
    words: list[dict[str, Any]],
    wav_path: str,
    transcript: str,
) -> dict[str, Any]:
    """Fluency-only score for open-ended speech (Picture Talk, Story Teller).

    Identical to `Scorer.score_session` minus coverage — the composite fluency_score
    is the pure disfluency (fluency-quality) score, since there is no reference to
    align against.
    """
    total_words = len(words)
    fluency_quality = _free_scorer.calculate_fluency_quality_score(disfluencies, total_words)
    return {
        "fluency_score": fluency_quality,          # no coverage blend for free speech
        "coverage_score": None,                    # N/A without a reference
        "fluency_quality_score": fluency_quality,
        "pss": _free_scorer.calculate_pss(disfluencies, words),
        "confidence_score": _free_scorer.calculate_confidence_score(words, wav_path),
        "clarity_score": _free_scorer.calculate_clarity_score(words),
        "words_per_minute": _free_scorer.calculate_wpm(words),
        "avg_pause_duration": _free_scorer.calculate_avg_pause(disfluencies),
        "stutter_frequency_percent": _free_scorer.calculate_stutter_frequency(disfluencies, total_words),
        "repetition_count": sum(1 for d in disfluencies if d.get("type") == "repetition"),
    }


async def _analyse_free_recording(
    content: bytes,
    filename: str | None,
    child_age: int,
    use_mock: bool,
) -> tuple[dict[str, Any], bytes]:
    """Reference-free analysis for open-ended speech, mirroring the conversation path.

    Uses the ML `/v1/analyse` endpoint (transcribe + text-layer detection) then
    enriches with local acoustic detection, and scores fluency-only. Returns the
    result dict plus the preprocessed WAV bytes (for optional S3 upload).
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
            transcript, words, ml_disfluencies = "this is what i think about it", [], []
        else:
            try:
                ml = await ml_client.analyse(
                    wav_bytes, filename="processed.wav", content_type="audio/wav"
                )
            except MLServiceError as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"{exc} Start the ML service on 8081, or pass use_mock=true.",
                ) from exc
            transcript, words, ml_disfluencies = ml["transcript"], ml["words"], ml["disfluencies"]

        disfluencies = enrich_with_acoustics(words, ml_disfluencies, wav_path)
        scores = _free_speech_scores(disfluencies, words, wav_path, transcript)
        flags = compute_attempt_flags(scores["fluency_score"], child_age)
        message = _free_feedback.generate_summary(scores, child_age)

    return {
        "transcript": transcript,
        "words": words,
        "disfluencies": disfluencies,
        "scores": scores,
        "should_retry": flags["should_retry"],
        "message": message,
        "reference_phrase": None,
    }, wav_bytes


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
