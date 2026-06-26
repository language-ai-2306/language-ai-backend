"""CLI to run the full analysis on a single audio file — no database needed.

Preprocesses the audio, sends it to the ML (transcription) service, then runs the
local analysis pipeline (detection → acoustic → recognition → scoring → feedback).

Usage:
    .venv/bin/python -m scripts.try_recognition <audio_file> "<reference phrase>" [child_age]

Example:
    .venv/bin/python -m scripts.try_recognition recording.wav "I see a snake" 8

Requires the ML service running on its configured URL (default :8081). If it's
unreachable, falls back to a mock transcript so you can still exercise the pipeline.
"""

import asyncio
import json
import os
import sys
import tempfile

from app.analysis import pipeline
from app.analysis.audio_utils import preprocess_audio, validate_audio
from app.services.ml_service import MLServiceError, ml_service


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 1

    audio_path, reference = sys.argv[1], sys.argv[2]
    child_age = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    if not os.path.exists(audio_path):
        print(f"File not found: {audio_path}")
        return 1

    with tempfile.TemporaryDirectory() as tmpdir:
        wav = os.path.join(tmpdir, "processed.wav")
        preprocess_audio(audio_path, wav)
        validate_audio(wav)
        with open(wav, "rb") as f:
            wav_bytes = f.read()

        try:
            transcription = asyncio.run(
                ml_service.transcribe(wav_bytes, filename="processed.wav", content_type="audio/wav")
            )
        except MLServiceError as exc:
            print(f"[warn] ML service unreachable ({exc}); using mock transcript. Start it on :8081 for real results.\n")
            transcription = ml_service.mock_transcribe(reference)

        result = pipeline.analyze(wav, transcription["transcript"], transcription["words"], reference, child_age)

    print("=== ANALYSIS ===")
    print(f"reference : {reference}")
    print(f"transcript: {result['transcript']}")
    print(json.dumps({k: v for k, v in result.items() if k != "words"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
