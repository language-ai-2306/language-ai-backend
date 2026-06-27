"""Analysis pipeline — turns a transcript + audio into disfluency analysis.

Runs entirely in the backend. Given a preprocessed WAV plus the transcript and
word timestamps (from the ML transcription service), it:

  1. detects lexical disfluencies (repetition / interjection / revision),
  2. detects acoustic disfluencies (block / prolongation) from the waveform,
  3. fuses them, picks the dominant disfluency, and identifies stress points,
  4. scores the attempt, and
  5. generates kid-friendly feedback + an age-banded summary.

No machine-learning model lives here — only rules and signal processing. The one
ML model in the system (Whisper) runs in the separate ML service and produces the
``transcript`` + ``words`` passed in.
"""

from typing import Any

from app.analysis.acoustic import analyze_audio
from app.analysis.detector import DisfluencyDetector
from app.analysis.feedback import FeedbackGenerator
from app.analysis.recognition import recognize
from app.analysis.scorer import Scorer, compute_attempt_flags

_detector = DisfluencyDetector()
_scorer = Scorer()
_feedback = FeedbackGenerator()


def analyze(
  wav_path: str,
  transcript: str,
  words: list[dict[str, Any]],
  reference_phrase: str,
  child_age: int,
) -> dict[str, Any]:
  """Run the full analysis on an already-transcribed attempt."""
  text_disfluencies = _detector.detect_all(transcript, words, reference_phrase)
  features = analyze_audio(wav_path)
  recognition = recognize(words, text_disfluencies, features)
  disfluencies = recognition["disfluencies"]

  scores = _scorer.score_session(disfluencies, words, wav_path, transcript, reference_phrase)
  attempt = compute_attempt_flags(scores["fluency_score"], child_age)
  message = _feedback.generate_summary(scores, child_age)

  return {
    "transcript": transcript,
    "words": words,
    "disfluencies": disfluencies,
    "recognition": {
      "dominant_disfluency": recognition["dominant_disfluency"],
      "dominant_confidence": recognition["dominant_confidence"],
      "impact_by_type": recognition["impact_by_type"],
      "stress_words": recognition["stress_words"],
      "stress_sounds": recognition["stress_sounds"],
    },
    "scores": scores,
    "should_retry": attempt["should_retry"],
    "message": message,
  }
