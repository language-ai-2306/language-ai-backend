"""Fluency, confidence, and clarity scoring."""

import logging
from typing import Any

import librosa
import numpy as np

logger = logging.getLogger(__name__)

DEDUCTIONS: dict[str, dict[str, int]] = {
  "repetition": {"mild": 2, "moderate": 3, "severe": 5},
  "prolongation": {"mild": 3, "moderate": 4, "severe": 6},
  "block": {"mild": 4, "moderate": 5, "severe": 7},
  "interjection": {"mild": 1, "moderate": 2, "severe": 3},
  "revision": {"mild": 2, "moderate": 3, "severe": 4},
}


class Scorer:
  # Phrases up to this many words are scored at full weight. Most practice
  # phrases for our 5–14 age group are short, and a stutter in a short phrase is
  # exactly what we want the score to reflect — so short phrases are NOT
  # discounted. Only longer phrases dampen per-event penalties (one stumble in a
  # long sentence should not tank the score).
  FULL_WEIGHT_LEN = 6
  MIN_TOLERANCE = 0.4

  def _length_tolerance_factor(self, total_words: int) -> float:
    """Per-event penalty weight. 1.0 for short phrases, easing toward
    ``MIN_TOLERANCE`` as phrases get long."""
    if total_words <= self.FULL_WEIGHT_LEN:
      return 1.0
    return max(self.MIN_TOLERANCE, self.FULL_WEIGHT_LEN / total_words)

  def calculate_fluency_score(self, disfluencies: list[dict[str, Any]], total_words: int) -> int:
    score = 100.0
    tolerance = self._length_tolerance_factor(total_words)

    for disfluency in disfluencies:
      dtype = disfluency.get("type", "")
      severity = disfluency.get("severity", "mild")
      deduction_table = DEDUCTIONS.get(dtype, {})
      deduction = deduction_table.get(severity, 1)
      score -= deduction * tolerance

    return int(max(0, min(100, round(score))))

  def _speaking_rate_consistency(self, audio_path: str, transcript_words: list[dict[str, Any]]) -> float:
    if not transcript_words:
      return 50.0

    try:
      y, sr = librosa.load(audio_path, sr=16000, mono=True)
    except Exception:
      logger.warning("Could not load audio for consistency scoring")
      return 50.0

    if len(y) == 0:
      return 0.0

    frame_length = 512
    hop_length = 256
    rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]

    if len(rms) < 2:
      return 50.0

    times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_length)
    word_energies: list[float] = []

    for word in transcript_words:
      mask = (times >= word["start"]) & (times <= word["end"])
      if np.any(mask):
        word_energies.append(float(np.mean(rms[mask])))

    if len(word_energies) < 2:
      return 70.0

    mean_energy = np.mean(word_energies)
    if mean_energy == 0:
      return 50.0

    cv = float(np.std(word_energies) / mean_energy)
    consistency = max(0.0, min(100.0, 100.0 - cv * 100.0))
    return consistency

  def calculate_confidence_score(
    self, transcript_words: list[dict[str, Any]], audio_path: str
  ) -> int:
    if not transcript_words:
      return 0

    avg_whisper_conf = np.mean([w.get("confidence", 0.0) for w in transcript_words])
    whisper_score = avg_whisper_conf * 100.0
    consistency_score = self._speaking_rate_consistency(audio_path, transcript_words)

    combined = 0.6 * whisper_score + 0.4 * consistency_score
    return int(max(0, min(100, round(combined))))

  def calculate_clarity_score(self, transcript_words: list[dict[str, Any]]) -> int:
    if not transcript_words:
      return 0

    avg_conf = np.mean([w.get("confidence", 0.0) for w in transcript_words])
    return int(max(0, min(100, round(avg_conf * 100))))

  def calculate_wpm(self, transcript_words: list[dict[str, Any]]) -> float:
    if not transcript_words:
      return 0.0

    total_words = len(transcript_words)
    total_duration = transcript_words[-1]["end"] - transcript_words[0]["start"]
    if total_duration <= 0:
      return 0.0

    return round(total_words / (total_duration / 60.0), 1)

  def calculate_avg_pause(self, disfluencies: list[dict[str, Any]]) -> float:
    """Average duration of the *disfluent* pauses (acoustic blocks).

    Whisper word timestamps are contiguous, so gaps between them are ~0 and tell
    us nothing about stuttering. The meaningful pauses are the silent blocks the
    acoustic layer found — those are what we report.
    """
    pauses = [
      float(d.get("pause_duration", 0.0))
      for d in disfluencies
      if d.get("type") == "block"
    ]
    pauses = [p for p in pauses if p > 0]
    if not pauses:
      return 0.0
    return round(float(np.mean(pauses)), 2)

  def calculate_stutter_frequency(
    self, disfluencies: list[dict[str, Any]], total_words: int
  ) -> float:
    """Percentage of words carrying a core stutter (block / prolongation /
    repetition). Counts distinct affected words so the result stays in 0–100 —
    an event count over words could exceed 100 and is not a real frequency.

    Relies on the recognition layer having tagged each acoustic event with the
    word it sits on; events without a word still count as one affected unit.
    """
    if total_words == 0:
      return 0.0

    stutter_types = {"repetition", "prolongation", "block"}
    affected: set[str] = set()
    for i, d in enumerate(disfluencies):
      if d.get("type") in stutter_types:
        affected.add(d.get("word") or f"__event_{i}")
    return round(min(len(affected), total_words) / total_words * 100, 1)

  def score_session(
    self,
    disfluencies: list[dict[str, Any]],
    transcript_words: list[dict[str, Any]],
    audio_path: str,
  ) -> dict[str, Any]:
    total_words = len(transcript_words)

    return {
      "fluency_score": self.calculate_fluency_score(disfluencies, total_words),
      "confidence_score": self.calculate_confidence_score(transcript_words, audio_path),
      "clarity_score": self.calculate_clarity_score(transcript_words),
      "words_per_minute": self.calculate_wpm(transcript_words),
      "avg_pause_duration": self.calculate_avg_pause(disfluencies),
      "stutter_frequency_percent": self.calculate_stutter_frequency(disfluencies, total_words),
      "repetition_count": sum(1 for d in disfluencies if d.get("type") == "repetition"),
    }
