"""Audio analysis route — upload a recording and get full disfluency analysis.

No database required. This is the main entry point for the analysis pipeline.

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

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.analysis import pipeline
from app.analysis.audio_utils import preprocess_audio, validate_audio
from app.analysis.text_utils import normalise_text
from app.config.settings import settings
from app.services.ml_client import MLServiceError, ml_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/audio", tags=["audio"])

DEFAULT_REFERENCE_PHRASE = "sometimes I find it hard to say what I mean"
DEFAULT_CHILD_AGE = 8


@router.get("/defaults")
async def get_defaults() -> dict[str, Any]:
    return {
        "note": "No database required. Point ML_SERVICE_URL at your language-ai-ml (transcription) service.",
        "ml_service_url": settings.ml_service_url,
        "reference_phrase": DEFAULT_REFERENCE_PHRASE,
        "child_age": DEFAULT_CHILD_AGE,
        "endpoint": "POST /v1/audio/analyze (multipart: audio, reference_phrase, child_age, use_mock)",
    }


@router.post("/analyze")
async def analyze_upload(
    audio: UploadFile = File(...),
    reference_phrase: str = Form(default=DEFAULT_REFERENCE_PHRASE),
    child_age: int = Form(default=DEFAULT_CHILD_AGE, ge=5, le=14),
    use_mock: bool = Form(default=False),
) -> dict[str, Any]:
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
            wav_path, transcription["transcript"], transcription["words"], reference_phrase, child_age
        )

    result["reference_phrase"] = normalise_text(reference_phrase)
    return result
