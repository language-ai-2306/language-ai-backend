"""Client for the ML service (transcription + TTS + disfluency analysis).

Transcription: returns transcript + word-level timestamps.
Analyse: transcription + timestamp-based disfluency detection in one call.
TTS: returns raw WAV bytes synthesised by Coqui XTTS-v2.
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

    async def analyse(
        self,
        audio_bytes: bytes,
        filename: str = "audio.wav",
        content_type: str = "audio/wav",
    ) -> dict[str, Any]:
        """Transcribe audio and run all four timestamp-based disfluency detectors in one ML call.

        Returns:
            {
                "transcript": str,
                "words": list[dict],          # Whisper word-level timestamps
                "disfluencies": list[dict],   # repetitions, prolongations, blocks, interjections
                "disfluency_count": int,
            }
        """
        url = f"{settings.ml_service_url.rstrip('/')}/v1/analyse"
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=settings.ml_service_timeout_seconds) as client:
                response = await client.post(
                    url, files={"audio": (filename, audio_bytes, content_type)}
                )
                response.raise_for_status()
                data = response.json()
                latency_ms = round((time.perf_counter() - started) * 1000, 2)
                logger.info("analyse latency_ms=%s", latency_ms)
                return {
                    "transcript": str(data.get("transcript", "")),
                    "words": list(data.get("words", [])),
                    "disfluencies": list(data.get("disfluencies", [])),
                    "disfluency_count": int(data.get("disfluency_count", 0)),
                }
        except httpx.TimeoutException as exc:
            raise MLServiceError("Analysis service timed out. Please try again.") from exc
        except httpx.HTTPError as exc:
            logger.error("Analyse request failed")
            raise MLServiceError("Analysis service is unavailable.") from exc

    async def synthesise(self, text: str) -> bytes:
        """Send text to the ML TTS endpoint and return raw WAV bytes."""
        url = f"{settings.ml_service_url.rstrip('/')}/v1/tts/speak"
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=settings.ml_service_timeout_seconds) as client:
                response = await client.post(url, json={"text": text})
                response.raise_for_status()
                latency_ms = round((time.perf_counter() - started) * 1000, 2)
                logger.info("tts latency_ms=%s", latency_ms)
                return response.content
        except httpx.TimeoutException as exc:
            raise MLServiceError("TTS service timed out.") from exc
        except httpx.HTTPError as exc:
            logger.error("TTS request failed")
            raise MLServiceError("TTS service is unavailable.") from exc

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
