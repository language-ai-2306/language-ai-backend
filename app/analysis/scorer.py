"""Fluency, confidence, and clarity scoring.

v2 scoring model — two-component system:
  final_score = round(0.6 × coverage_score + 0.4 × fluency_quality_score)

Coverage  — word alignment against the reference phrase (missing/substituted/extra words).
Fluency   — disfluency deductions calibrated to SSI-4 severity bands.

%SS (percentage syllables stuttered) is reported separately as a clinical metric
for speech-language pathologists; it does not affect the final score.

Retry flag — single threshold:
  should_retry=False  score ≥ threshold → advance to next node
  should_retry=True   score <  threshold → try again

  Age 5–7  : threshold=75  (natural disfluency rates are higher at this age)
  Age 8–10 : threshold=80
  Age 11–14: threshold=85  (maps to SSI-4 very-mild boundary, ~3% SS)

  Research basis:
    - Lidcombe clinical target: <1% SS — too strict for a practice game.
    - SSI-4 very-mild boundary ≈ 3% SS → maps to score ~85 in our system.
    - Clear binary feedback is better for children with speech anxiety than
      ambiguous "passed but try again" states (Lidcombe, CALMS therapy evidence).
"""

import logging
import re
from difflib import SequenceMatcher
from typing import Any

import librosa
import numpy as np

from app.analysis.text_utils import tokenise

logger = logging.getLogger(__name__)

# ── DEDUCTION TABLES ──────────────────────────────────────────────────────────
# Calibrated to SSI-4 severity bands: 5-10% SS ≈ mild, 10-20% ≈ moderate,
# 20%+ ≈ severe. For a 4-word phrase (~8 syllables) one event = 12.5% SS —
# already moderate territory, hence penalties much higher than the old table.

DEDUCTIONS: dict[str, dict[str, int]] = {
    "repetition":  {"mild": 5,  "moderate": 10, "severe": 14},  # word-level fallback
    "prolongation":{"mild": 6,  "moderate": 11, "severe": 16},
    "block":       {"mild": 10, "moderate": 16, "severe": 24},
    "interjection":{"mild": 2,  "moderate": 4,  "severe": 6},
    "revision":    {"mild": 3,  "moderate": 6,  "severe": 9},
}

# Repetition sub-table keyed by disfluency["character"]
# Sound-level reps are most severe (onset-based); word-level are least.
_REPETITION_DEDUCTIONS: dict[str, dict[str, int]] = {
    "sound":    {"mild": 9,  "moderate": 14, "severe": 20},
    "syllable": {"mild": 7,  "moderate": 12, "severe": 17},
    "word":     {"mild": 5,  "moderate": 10, "severe": 14},
}

# Coverage penalties
_MISSING_WORD    = 20
_SUBSTITUTED_WORD = 8
_EXTRA_WORD       = 3

# Final score weights
_COVERAGE_W = 0.6
_FLUENCY_W  = 0.4

# Age-adjusted pass threshold — single cutoff, two clean states.
# Below threshold: passed=False, should_retry=True  → "Try again!"
# At or above:     passed=True,  should_retry=False → "Great job, move on!"
#
# Thresholds map to SSI-4 very-mild boundary (~3% SS) for older children,
# with leniency for younger ages where natural disfluency rates are higher.
_AGE_PASS_THRESHOLDS: list[tuple[tuple[int, int], int]] = [
    ((5,  7),  75),
    ((8,  10), 80),
    ((11, 14), 85),
]
_DEFAULT_PASS_THRESHOLD = 85


def _pass_threshold_for_age(child_age: int) -> int:
    for (lo, hi), threshold in _AGE_PASS_THRESHOLDS:
        if lo <= child_age <= hi:
            return threshold
    return _DEFAULT_PASS_THRESHOLD


def compute_attempt_flags(final_score: int, child_age: int) -> dict[str, bool]:
    """Return should_retry for the given score and age.

    should_retry=True  → score < threshold, UI should prompt retry
    should_retry=False → score ≥ threshold, advance to next node
    """
    return {
        "should_retry": final_score < _pass_threshold_for_age(child_age),
    }


# ── HELPERS ───────────────────────────────────────────────────────────────────

def _syllable_count(word: str) -> int:
    """Rough syllable count via vowel-cluster heuristic."""
    cleaned = re.sub(r"[^a-z]", "", word.lower())
    return max(1, len(re.findall(r"[aeiouy]+", cleaned)))


def _deduction_for(disfluency: dict[str, Any]) -> float:
    dtype = disfluency.get("type", "")
    severity = disfluency.get("severity", "mild")
    if dtype == "repetition":
        char = disfluency.get("character", "word")
        table = _REPETITION_DEDUCTIONS.get(char, _REPETITION_DEDUCTIONS["word"])
    else:
        table = DEDUCTIONS.get(dtype, {})
    return float(table.get(severity, 1))


# ── SCORER ────────────────────────────────────────────────────────────────────

class Scorer:
    # Phrases up to this many words are scored at full per-event weight.
    FULL_WEIGHT_LEN = 6
    MIN_TOLERANCE   = 0.4

    def _length_tolerance(self, total_words: int) -> float:
        if total_words <= self.FULL_WEIGHT_LEN:
            return 1.0
        return max(self.MIN_TOLERANCE, self.FULL_WEIGHT_LEN / total_words)

    # ── Coverage ──────────────────────────────────────────────────────────────

    def calculate_coverage_score(self, transcript: str, reference_phrase: str) -> int:
        """Align transcript tokens against reference tokens and penalise gaps."""
        ref_tokens   = tokenise(reference_phrase)
        trans_tokens = tokenise(transcript)

        if not ref_tokens:
            return 100
        if not trans_tokens:
            # Nothing was said — penalise every reference word as missing.
            return max(0, 100 - len(ref_tokens) * _MISSING_WORD)

        matcher = SequenceMatcher(None, ref_tokens, trans_tokens, autojunk=False)
        penalty = 0.0

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                pass
            elif tag == "delete":
                # Words in ref not spoken — missing words.
                penalty += (i2 - i1) * _MISSING_WORD
            elif tag == "insert":
                # Words spoken not in ref — extra words.
                penalty += (j2 - j1) * _EXTRA_WORD
            elif tag == "replace":
                ref_len   = i2 - i1
                trans_len = j2 - j1
                # The shorter side = substitutions, longer side = missing/extra.
                matched   = min(ref_len, trans_len)
                penalty  += matched * _SUBSTITUTED_WORD
                if ref_len > trans_len:
                    penalty += (ref_len - trans_len) * _MISSING_WORD
                elif trans_len > ref_len:
                    penalty += (trans_len - ref_len) * _EXTRA_WORD

        return int(max(0, min(100, round(100 - penalty))))

    # ── Fluency quality ───────────────────────────────────────────────────────

    def calculate_fluency_quality_score(
        self, disfluencies: list[dict[str, Any]], total_words: int
    ) -> int:
        """Pure disfluency score — word coverage not included."""
        score     = 100.0
        tolerance = self._length_tolerance(total_words)
        for d in disfluencies:
            score -= _deduction_for(d) * tolerance
        return int(max(0, min(100, round(score))))

    # ── %SS ───────────────────────────────────────────────────────────────────

    def calculate_pss(
        self,
        disfluencies: list[dict[str, Any]],
        transcript_words: list[dict[str, Any]],
    ) -> float:
        """Percentage Syllables Stuttered — clinical metric matching SSI-4."""
        stutter_types = {"block", "prolongation", "repetition"}
        stutter_count = sum(1 for d in disfluencies if d.get("type") in stutter_types)
        total_syllables = sum(_syllable_count(w.get("word", "")) for w in transcript_words)
        if total_syllables == 0:
            return 0.0
        return round(stutter_count / total_syllables * 100, 1)

    # ── Confidence / clarity / WPM / pause (unchanged) ───────────────────────

    def _speaking_rate_consistency(
        self, audio_path: str, transcript_words: list[dict[str, Any]]
    ) -> float:
        if not transcript_words:
            return 50.0
        try:
            y, sr = librosa.load(audio_path, sr=16000, mono=True)
        except Exception:
            logger.warning("Could not load audio for consistency scoring")
            return 50.0
        if len(y) == 0:
            return 0.0
        frame_length, hop_length = 512, 256
        rms   = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
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
        return max(0.0, min(100.0, 100.0 - cv * 100.0))

    def calculate_confidence_score(
        self, transcript_words: list[dict[str, Any]], audio_path: str
    ) -> int:
        if not transcript_words:
            return 0
        avg_whisper_conf  = np.mean([w.get("confidence", 0.0) for w in transcript_words])
        consistency_score = self._speaking_rate_consistency(audio_path, transcript_words)
        combined = 0.6 * avg_whisper_conf * 100.0 + 0.4 * consistency_score
        return int(max(0, min(100, round(combined))))

    def calculate_clarity_score(self, transcript_words: list[dict[str, Any]]) -> int:
        if not transcript_words:
            return 0
        avg_conf = np.mean([w.get("confidence", 0.0) for w in transcript_words])
        return int(max(0, min(100, round(avg_conf * 100))))

    def calculate_wpm(self, transcript_words: list[dict[str, Any]]) -> float:
        if not transcript_words:
            return 0.0
        total_duration = transcript_words[-1]["end"] - transcript_words[0]["start"]
        if total_duration <= 0:
            return 0.0
        return round(len(transcript_words) / (total_duration / 60.0), 1)

    def calculate_avg_pause(self, disfluencies: list[dict[str, Any]]) -> float:
        pauses = [
            float(d.get("pause_duration", 0.0))
            for d in disfluencies
            if d.get("type") == "block"
        ]
        pauses = [p for p in pauses if p > 0]
        return round(float(np.mean(pauses)), 2) if pauses else 0.0

    def calculate_stutter_frequency(
        self, disfluencies: list[dict[str, Any]], total_words: int
    ) -> float:
        if total_words == 0:
            return 0.0
        stutter_types = {"repetition", "prolongation", "block"}
        affected: set[str] = set()
        for i, d in enumerate(disfluencies):
            if d.get("type") in stutter_types:
                affected.add(d.get("word") or f"__event_{i}")
        return round(min(len(affected), total_words) / total_words * 100, 1)

    # ── Main entry ────────────────────────────────────────────────────────────

    def score_session(
        self,
        disfluencies: list[dict[str, Any]],
        transcript_words: list[dict[str, Any]],
        audio_path: str,
        transcript: str = "",
        reference_phrase: str = "",
    ) -> dict[str, Any]:
        total_words = len(transcript_words)

        coverage_score        = self.calculate_coverage_score(transcript, reference_phrase)
        fluency_quality_score = self.calculate_fluency_quality_score(disfluencies, total_words)
        final_score           = int(round(_COVERAGE_W * coverage_score + _FLUENCY_W * fluency_quality_score))

        return {
            "fluency_score":          final_score,
            "coverage_score":         coverage_score,
            "fluency_quality_score":  fluency_quality_score,
            "pss":                    self.calculate_pss(disfluencies, transcript_words),
            "confidence_score":       self.calculate_confidence_score(transcript_words, audio_path),
            "clarity_score":          self.calculate_clarity_score(transcript_words),
            "words_per_minute":       self.calculate_wpm(transcript_words),
            "avg_pause_duration":     self.calculate_avg_pause(disfluencies),
            "stutter_frequency_percent": self.calculate_stutter_frequency(disfluencies, total_words),
            "repetition_count":       sum(1 for d in disfluencies if d.get("type") == "repetition"),
        }
