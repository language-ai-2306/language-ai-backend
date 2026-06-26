"""Recognition layer: fuse text + acoustic detections into an answer.

Given the text-based disfluencies (from ``DisfluencyDetector``) and the acoustic
disfluencies (from ``acoustic.py``), this module answers the two recognition
questions:

  1. What type of stutter is *dominant* for this attempt?
  2. Which *words* and *sounds* did the child get stuck on (the stress points)?

It does NOT decide what to tell the child — the coaching/response model is
intentionally out of scope here.

Notes on accuracy:
  • Block / prolongation come from the acoustic layer (reliable).
  • Repetition / interjection / revision come from the text layer.
  • Stress *sounds* are best-effort: blocks and repetitions almost always sit on
    a word's onset (clinically true), so we report the first sound. Prolongation
    position is approximated from timing. True phoneme-level localisation needs a
    phoneme model + forced alignment (next step).
"""

from __future__ import annotations

import re
from typing import Any

from app.analysis.acoustic import AcousticFeatures, detect_all_acoustic
from app.analysis.scorer import DEDUCTIONS

# Tie-break order when two types have equal impact: core stuttering behaviours win.
PRIORITY = ["block", "prolongation", "repetition", "revision", "interjection"]

# These are not the child struggling on a target phrase word, so they don't
# contribute a "stress word/sound".
NON_STRESS_TYPES = {"interjection", "revision"}

# Acoustic layer is authoritative for these types (now includes sound repetition,
# which the acoustic layer detects via onset-burst similarity).
ACOUSTIC_TYPES = {"block", "prolongation", "repetition"}

# Conflict resolution (Zhang 2508.16681): when events collide, the more severe
# behaviour wins, and events must be at least this far apart.
MIN_EVENT_SEPARATION_S = 0.1


def _precedence(d: dict[str, Any]) -> int:
  """Lower = wins. blocks > sound-reps > prolongations > word-reps > revision > interjection."""
  dtype = d.get("type")
  if dtype == "block":
    return 0
  if dtype == "repetition" and d.get("character") == "sound":
    return 1
  if dtype == "prolongation":
    return 2
  if dtype == "repetition":
    return 3
  if dtype == "revision":
    return 4
  if dtype == "interjection":
    return 5
  return 6


def _resolve_conflicts(disfluencies: list[dict[str, Any]]) -> list[dict[str, Any]]:
  """Drop lower-precedence events that overlap or sit within MIN_EVENT_SEPARATION_S
  of a higher-precedence one, so colliding detections don't double-count."""
  ordered = sorted(disfluencies, key=lambda d: (_precedence(d), d.get("timestamp_start", 0.0)))
  kept: list[dict[str, Any]] = []
  for d in ordered:
    ds, de = d.get("timestamp_start", 0.0), d.get("timestamp_end", 0.0)
    conflict = False
    for k in kept:
      ks, ke = k.get("timestamp_start", 0.0), k.get("timestamp_end", 0.0)
      gap = max(ds, ks) - min(de, ke)  # <0 means overlap; else the gap between them
      if gap < MIN_EVENT_SEPARATION_S:
        conflict = True
        break
    if not conflict:
      kept.append(d)
  kept.sort(key=lambda d: d.get("timestamp_start", 0.0))
  return kept


def _weight(disfluency: dict[str, Any]) -> float:
  table = DEDUCTIONS.get(disfluency.get("type", ""), {})
  return float(table.get(disfluency.get("severity", "mild"), 1))


def _overlaps(a: dict[str, Any], b: dict[str, Any]) -> bool:
  a0, a1 = a.get("timestamp_start", 0.0), a.get("timestamp_end", 0.0)
  b0, b1 = b.get("timestamp_start", 0.0), b.get("timestamp_end", 0.0)
  return a0 < b1 and b0 < a1


def _suppress_prolongations_in_blocks(disfluencies: list[dict[str, Any]]) -> list[dict[str, Any]]:
  """Drop any prolongation that overlaps a block.

  A stretch of silence is a block, never a prolongation. If both fire on the same
  span (e.g. a word whose Whisper duration was stretched over a real silence),
  the block wins and the overlapping prolongation is discarded.
  """
  blocks = [d for d in disfluencies if d.get("type") == "block"]
  if not blocks:
    return disfluencies
  return [
    d
    for d in disfluencies
    if not (d.get("type") == "prolongation" and any(_overlaps(d, b) for b in blocks))
  ]


def fuse(
  text_disfluencies: list[dict[str, Any]],
  acoustic_disfluencies: list[dict[str, Any]],
) -> list[dict[str, Any]]:
  """Merge text + acoustic detections, preferring acoustic for block/prolongation.

  A text-layer block/prolongation is dropped only if an acoustic detection of the
  same type overlaps it (the acoustic one is more reliable). If acoustic missed
  it, the text detection is kept as a fallback. Finally, any prolongation sitting
  inside a block is suppressed (a silence is a block, not a held sound).
  """
  fused: list[dict[str, Any]] = list(acoustic_disfluencies)
  for d in text_disfluencies:
    if d.get("type") in ACOUSTIC_TYPES and any(
      a.get("type") == d.get("type") and _overlaps(a, d) for a in acoustic_disfluencies
    ):
      continue
    fused.append(d)
  fused = _suppress_prolongations_in_blocks(fused)
  fused.sort(key=lambda d: d.get("timestamp_start", 0.0))
  return fused


def dominant_disfluency(disfluencies: list[dict[str, Any]]) -> dict[str, Any]:
  """Pick the single dominant disfluency type by severity-weighted impact."""
  if not disfluencies:
    return {"type": None, "confidence": 0.0, "impact_by_type": {}}

  impact: dict[str, float] = {}
  for d in disfluencies:
    dtype = d.get("type")
    if not dtype:
      continue
    impact[dtype] = impact.get(dtype, 0.0) + _weight(d)

  if not impact:
    return {"type": None, "confidence": 0.0, "impact_by_type": {}}

  total = sum(impact.values())
  best = sorted(
    impact.items(),
    key=lambda kv: (-kv[1], PRIORITY.index(kv[0]) if kv[0] in PRIORITY else len(PRIORITY)),
  )[0][0]

  return {
    "type": best,
    "confidence": round(impact[best] / total, 2) if total else 0.0,
    "impact_by_type": {k: round(v, 2) for k, v in impact.items()},
  }


# --- stress-point helpers -----------------------------------------------------


def _clean(word: str) -> str:
  return re.sub(r"[^A-Za-z']", "", word or "").lower()


def _first_sound(word: str) -> str:
  cleaned = _clean(word)
  return cleaned[0] if cleaned else ""


def _sound_at_fraction(word: str, frac: float) -> str:
  cleaned = _clean(word)
  if not cleaned:
    return ""
  idx = min(len(cleaned) - 1, max(0, int(frac * len(cleaned))))
  return cleaned[idx]


def _word_index_containing(words: list[dict[str, Any]], t: float, fallback_word: str | None) -> int | None:
  for i, w in enumerate(words):
    if w["start"] - 0.05 <= t <= w["end"] + 0.05:
      return i
  if fallback_word:
    target = _clean(fallback_word)
    for i, w in enumerate(words):
      if _clean(w["word"]) == target:
        return i
  return None


def _word_index_after(words: list[dict[str, Any]], t: float) -> int | None:
  for i, w in enumerate(words):
    if w["start"] >= t - 0.05:
      return i
  return len(words) - 1 if words else None


def _word_index_overlap(words: list[dict[str, Any]], d: dict[str, Any]) -> int | None:
  ds, de = d.get("timestamp_start", 0.0), d.get("timestamp_end", 0.0)
  best, best_overlap = None, 0.0
  for i, w in enumerate(words):
    overlap = min(de, w["end"]) - max(ds, w["start"])
    if overlap > best_overlap:
      best, best_overlap = i, overlap
  return best


def identify_stress(
  disfluencies: list[dict[str, Any]],
  words: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
  """Identify which words and sounds the child got stuck on.

  Returns (stress_words, stress_sounds):
    stress_words  — ranked by severity-weighted impact, most stuck first.
    stress_sounds — per-event {word, sound, type}; ``approximate`` flags timing-
                    based localisation (prolongation) vs onset (block/repetition).
  """
  word_scores: dict[int, dict[str, Any]] = {}
  sounds: list[dict[str, Any]] = []

  for d in disfluencies:
    dtype = d.get("type")
    if dtype in NON_STRESS_TYPES or not words:
      continue

    idx: int | None = None
    sound = ""
    approximate = False

    if dtype == "block":
      # A block sits before a word and implicates that word's onset.
      idx = _word_index_after(words, d.get("timestamp_end", d.get("timestamp_start", 0.0)))
      if idx is not None:
        sound = _first_sound(words[idx]["word"])
    elif dtype == "repetition":
      idx = _word_index_containing(words, d.get("timestamp_start", 0.0), d.get("word"))
      if idx is not None:
        sound = _first_sound(words[idx]["word"])  # repetitions cluster on onsets
    elif dtype == "prolongation":
      idx = _word_index_overlap(words, d)
      if idx is not None:
        w = words[idx]
        if d.get("character") == "fricative":
          # A held fricative (/s/, /sh/, /f/) is the word's onset consonant —
          # acoustically grounded, so this is not an approximation.
          sound = _first_sound(w["word"])
        else:
          span = max(w["end"] - w["start"], 1e-6)
          center = (d.get("timestamp_start", w["start"]) + d.get("timestamp_end", w["end"])) / 2
          frac = min(1.0, max(0.0, (center - w["start"]) / span))
          sound = _sound_at_fraction(w["word"], frac)
          approximate = True

    if idx is None:
      continue

    # Attach the resolved word (and sound) to the acoustic event so downstream
    # feedback can name it (acoustic detections only carry timestamps on their own).
    d.setdefault("word", _clean(words[idx]["word"]))
    if sound:
      d.setdefault("sound", sound)

    entry = word_scores.setdefault(
      idx, {"word": _clean(words[idx]["word"]), "impact": 0.0, "types": set()}
    )
    entry["impact"] += _weight(d)
    entry["types"].add(dtype)

    if sound:
      sounds.append(
        {"word": _clean(words[idx]["word"]), "sound": sound, "type": dtype, "approximate": approximate}
      )

  stress_words = [
    {
      "word": v["word"],
      "impact": round(v["impact"], 2),
      "disfluency_types": sorted(v["types"]),
    }
    for _, v in sorted(word_scores.items(), key=lambda kv: -kv[1]["impact"])
  ]
  return stress_words, sounds


def recognize(
  words: list[dict[str, Any]],
  text_disfluencies: list[dict[str, Any]],
  features: AcousticFeatures | None,
) -> dict[str, Any]:
  """Top-level recognition: fuse layers, pick dominant, find stress points."""
  acoustic_disfluencies = detect_all_acoustic(features)
  fused = fuse(text_disfluencies, acoustic_disfluencies)
  fused = _resolve_conflicts(fused)
  dominant = dominant_disfluency(fused)
  stress_words, stress_sounds = identify_stress(fused, words)

  return {
    "dominant_disfluency": dominant["type"],
    "dominant_confidence": dominant["confidence"],
    "impact_by_type": dominant["impact_by_type"],
    "stress_words": stress_words,
    "stress_sounds": stress_sounds,
    "disfluencies": fused,
  }
