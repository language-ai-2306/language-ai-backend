"""Rule-based disfluency detection via transcript vs reference comparison."""

import difflib
from typing import Any

from app.analysis.text_utils import normalise_text, tokenise, word_frequency


class DisfluencyDetector:
  FILLER_WORDS = [
    "um",
    "uh",
    "like",
    "you know",
    "so",
    "well",
    "er",
    "hmm",
    "ah",
    "okay",
    "right",
  ]

  def _word_key(self, word_entry: dict[str, Any]) -> str:
    return normalise_text(word_entry.get("word", ""))

  def _severity_from_repeat_count(self, extra_count: int) -> str:
    if extra_count >= 3:
      return "severe"
    if extra_count >= 2:
      return "moderate"
    return "mild"

  def detect_repetitions(
    self, transcript_words: list[dict[str, Any]], reference_words: list[str]
  ) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    ref_freq = word_frequency(reference_words)
    trans_tokens = [self._word_key(w) for w in transcript_words]
    trans_freq = word_frequency(trans_tokens)

    # Words appearing more often in transcript than reference
    for word, count in trans_freq.items():
      if not word:
        continue
      ref_count = ref_freq.get(word, 0)
      # Require an actual repeat (said at least twice). A word that appears only
      # once but isn't in the reference is a substitution/mistranscription
      # (e.g. "sometime" vs "sometimes"), not a repetition — flagging those
      # produced false positives.
      if count >= 2 and count > ref_count:
        extra = count - ref_count
        word_entries = [w for w in transcript_words if self._word_key(w) == word]
        if word_entries:
          results.append(
            {
              "type": "repetition",
              "word": word,
              "timestamp_start": word_entries[0]["start"],
              "timestamp_end": word_entries[-1]["end"],
              "severity": self._severity_from_repeat_count(extra),
            }
          )

    # Consecutive repeated words (I I, the the)
    i = 0
    while i < len(transcript_words) - 1:
      current = self._word_key(transcript_words[i])
      j = i + 1
      while j < len(transcript_words) and self._word_key(transcript_words[j]) == current:
        j += 1
      run_length = j - i
      if run_length >= 2 and current:
        extra = run_length - 1
        entry = {
          "type": "repetition",
          "word": current,
          "timestamp_start": transcript_words[i]["start"],
          "timestamp_end": transcript_words[j - 1]["end"],
          "severity": self._severity_from_repeat_count(extra),
        }
        if not self._is_duplicate(results, entry):
          results.append(entry)
      i = j if run_length >= 2 else i + 1

    return results

  def detect_interjections(
    self, transcript_words: list[dict[str, Any]], reference_words: list[str]
  ) -> list[dict[str, Any]]:
    # Only true filler words count as interjections. Previously *any* word not in
    # the reference was flagged, which over-fired on misheard words and off-script
    # speech — and, now that we pick a single dominant disfluency, that noise
    # could wrongly make "interjection" dominant. ``reference_words`` is kept in
    # the signature for compatibility but is intentionally no longer used here.
    results: list[dict[str, Any]] = []
    normalised_fillers = {normalise_text(f) for f in self.FILLER_WORDS}

    for entry in transcript_words:
      word = self._word_key(entry)
      if not word:
        continue

      if word in normalised_fillers:
        results.append(
          {
            "type": "interjection",
            "word": word,
            "timestamp_start": entry["start"],
            "timestamp_end": entry["end"],
            "severity": "mild",
          }
        )

    return results

  def detect_revisions(
    self,
    transcript: str,
    reference: str,
    transcript_words: list[dict[str, Any]] | None = None,
  ) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    trans_tokens = tokenise(transcript)
    ref_tokens = tokenise(reference)

    if len(trans_tokens) < 2 or len(ref_tokens) < 2:
      return results

    # Prefix restart: transcript restarts with beginning of reference phrase
    for i in range(1, len(trans_tokens)):
      max_k = min(len(ref_tokens), len(trans_tokens) - i)
      for k in range(2, max_k + 1):
        if trans_tokens[i : i + k] == ref_tokens[:k]:
          segment = " ".join(trans_tokens[:i])
          timestamp_start = 0.0
          timestamp_end = 0.0
          if transcript_words:
            timestamp_start = transcript_words[0]["start"]
            end_idx = min(i, len(transcript_words)) - 1
            if end_idx >= 0:
              timestamp_end = transcript_words[end_idx]["end"]

          entry = {
            "type": "revision",
            "segment": segment,
            "timestamp_start": timestamp_start,
            "timestamp_end": timestamp_end,
            "severity": "moderate",
          }
          if not self._is_duplicate_type_segment(results, entry):
            results.append(entry)
          break

    # difflib: inserted segments mid-phrase. Compare TOKEN lists (not strings) so
    # the opcode indices are word positions — they must line up with trans_tokens
    # and transcript_words. Diffing the raw strings returns *character* offsets,
    # which then mis-slice the word list and produce garbled revision segments.
    matcher = difflib.SequenceMatcher(None, ref_tokens, trans_tokens)

    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
      if tag != "insert" or j1 == 0:
        continue

      segment_tokens = trans_tokens[j1:j2]
      if len(segment_tokens) < 2:
        continue

      segment = " ".join(segment_tokens)
      timestamp_start = 0.0
      timestamp_end = 0.0
      if transcript_words and j1 < len(transcript_words):
        timestamp_start = transcript_words[j1]["start"]
        end_idx = min(j2, len(transcript_words)) - 1
        if end_idx >= 0:
          timestamp_end = transcript_words[end_idx]["end"]

      entry = {
        "type": "revision",
        "segment": segment,
        "timestamp_start": timestamp_start,
        "timestamp_end": timestamp_end,
        "severity": "moderate",
      }
      if not self._is_duplicate_type_segment(results, entry):
        results.append(entry)

    return results

  def _is_duplicate_type_segment(
    self, existing: list[dict[str, Any]], candidate: dict[str, Any]
  ) -> bool:
    for item in existing:
      if item.get("type") == candidate.get("type") and item.get("segment") == candidate.get(
        "segment"
      ):
        return True
    return False

  def _is_duplicate(self, existing: list[dict[str, Any]], candidate: dict[str, Any]) -> bool:
    for item in existing:
      if (
        item.get("type") == candidate.get("type")
        and item.get("word") == candidate.get("word")
        and abs(item.get("timestamp_start", 0) - candidate.get("timestamp_start", 0)) < 0.05
      ):
        return True
    return False

  def _overlaps(self, a: dict[str, Any], b: dict[str, Any]) -> bool:
    if a.get("type") != b.get("type"):
      return False
    start_a = a.get("timestamp_start", 0)
    end_a = a.get("timestamp_end", 0)
    start_b = b.get("timestamp_start", 0)
    end_b = b.get("timestamp_end", 0)
    return start_a < end_b and start_b < end_a

  def _deduplicate(self, disfluencies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not disfluencies:
      return []

    sorted_items = sorted(disfluencies, key=lambda d: d.get("timestamp_start", 0))
    deduped: list[dict[str, Any]] = []

    for item in sorted_items:
      duplicate = False
      for kept in deduped:
        if self._overlaps(item, kept) and item.get("type") == kept.get("type"):
          duplicate = True
          break
      if not duplicate:
        deduped.append(item)

    return deduped

  def detect_all(
    self,
    transcript: str,
    transcript_words: list[dict[str, Any]],
    reference_phrase: str,
  ) -> list[dict[str, Any]]:
    # The text layer detects only the lexical disfluencies it can detect
    # reliably (repetition / interjection / revision). Block and prolongation are
    # owned by the acoustic layer (app/analysis/acoustic.py), which measures the
    # waveform directly — Whisper word timestamps stretch over silence, so a
    # text/timestamp-based block or prolongation detector fires false positives.
    reference_words = tokenise(reference_phrase)

    all_disfluencies: list[dict[str, Any]] = []
    all_disfluencies.extend(self.detect_repetitions(transcript_words, reference_words))
    all_disfluencies.extend(self.detect_interjections(transcript_words, reference_words))
    all_disfluencies.extend(
      self.detect_revisions(transcript, reference_phrase, transcript_words)
    )

    return self._deduplicate(all_disfluencies)
