"""Client for the ML transcription service.

The ML service is now transcription-only: it returns a transcript + word-level
timestamps. All disfluency analysis happens locally in app/analysis/.
"""

import logging
import time
from typing import Any

import httpx

from app.config.settings import settings

logger = logging.getLogger(__name__)


class MLServiceError(Exception):
    pass


class MLService:
    async def transcribe(
        self,
        audio_bytes: bytes,
        filename: str = "audio.wav",
        content_type: str = "audio/wav",
    ) -> dict[str, Any]:
        """Send a (preprocessed) WAV to the ML service and get transcript + words."""
        url = f"{settings.ml_service_url.rstrip('/')}/v1/transcribe"
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=settings.ml_service_timeout_seconds) as client:
                response = await client.post(
                    url, files={"audio": (filename, audio_bytes, content_type)}
                )
                response.raise_for_status()
                data = response.json()
                latency_ms = round((time.perf_counter() - started) * 1000, 2)
                logger.info("transcription latency_ms=%s", latency_ms)
                return {
                    "transcript": str(data.get("transcript", "")),
                    "words": list(data.get("words", [])),
                }
        except httpx.TimeoutException as exc:
            raise MLServiceError("Transcription service timed out. Please try again.") from exc
        except httpx.HTTPError as exc:
            logger.error("Transcription request failed")
            raise MLServiceError("Transcription service is unavailable.") from exc

    def mock_transcribe(self, reference_phrase: str) -> dict[str, Any]:
        """Dev fallback when the ML service is down: pretend the phrase was said cleanly."""
        words: list[dict[str, Any]] = []
        t = 0.0
        for token in reference_phrase.split():
            words.append(
                {"word": token, "start": round(t, 3), "end": round(t + 0.3, 3), "confidence": 0.9}
            )
            t += 0.4
        return {"transcript": reference_phrase, "words": words}


ml_client = MLService()
