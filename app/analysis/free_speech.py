"""Disfluency analysis for free conversational speech (no reference phrase).

The ML service's /v1/analyse endpoint handles transcription + timestamp-based
disfluency detection (repetitions, prolongations, blocks, interjections) in one
call. This module adds the waveform-based acoustic layer (librosa) on top of
those text-layer events to catch disfluencies that Whisper timestamps alone miss
(e.g. prolongations that manifest spectrally, not just in duration).

Call flow (from conversation.py):
    ml_result = await ml_client.analyse(audio_bytes)
    events = enrich_with_acoustics(ml_result["words"], ml_result["disfluencies"], wav_path)
"""

from typing import Any

from app.analysis.acoustic import analyze_audio
from app.analysis.recognition import detect_all_acoustic, fuse, _resolve_conflicts


def enrich_with_acoustics(
    words: list[dict[str, Any]],
    ml_disfluencies: list[dict[str, Any]],
    wav_path: str,
) -> list[dict[str, Any]]:
    """Merge ML-service disfluency events with waveform-based acoustic events.

    Args:
        words:            Word-level timestamps from Whisper (passed through from ML).
        ml_disfluencies:  Events already detected by the ML service (timestamp-based).
        wav_path:         Path to the preprocessed 16 kHz mono WAV file on disk.

    Returns:
        Deduplicated, time-sorted list of all disfluency events.
    """
    features = analyze_audio(wav_path)
    acoustic_events = detect_all_acoustic(features)

    combined = fuse(ml_disfluencies, acoustic_events)
    return _resolve_conflicts(combined)
