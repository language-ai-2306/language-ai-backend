"""Generate a synthetic seed for the evaluation set.

Writes controlled clips (held fricative, held vowel, silent block, fluent) with
KNOWN content into data/eval/synthetic/, plus their gold labels and cached
transcript/words into data/eval/labels.jsonl. This lets scripts/evaluate.py run
on day one with no real audio or ML service.

Synthetic clips are for *boundary* and *regression* testing — they are NOT a
substitute for real SLP-annotated child speech (see data/eval/README.md).

Usage:
    .venv/bin/python -m scripts.make_synthetic_eval
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "eval" / "synthetic"
LABELS = ROOT / "data" / "eval" / "labels.jsonl"
SR = 16000
rng = np.random.default_rng(0)


def vowel(dur: float, f0: float = 200.0, moving: bool = True) -> np.ndarray:
  """Voiced sound. moving=True -> changing spectrum (fluent speech); moving=False
  -> steady spectrum (a held/prolonged vowel)."""
  n = int(dur * SR)
  t = np.arange(n) / SR
  if moving:
    f0_t = f0 * (1 + 0.12 * np.sin(2 * np.pi * 3.0 * t))
    phase = 2 * np.pi * np.cumsum(f0_t) / SR
    emph = 1.5 + np.linspace(0, 2.0, n)
    sig = sum((0.3 / k) * np.sin(k * phase) * (1 + 0.4 * np.sin(emph * k)) for k in (1, 2, 3, 4))
    sig = sig + 0.01 * rng.standard_normal(n)
  else:
    sig = sum(0.3 / k * np.sin(2 * np.pi * f0 * k * t) for k in (1, 2, 3))
  return sig.astype(np.float32)


def fricative(dur: float, target_rms: float = 0.05, lo: float = 4500, hi: float = 7500) -> np.ndarray:
  """Band-limited high-frequency noise at a realistic /s/ level."""
  n = int(dur * SR)
  spec = np.fft.rfft(rng.standard_normal(n))
  freqs = np.fft.rfftfreq(n, 1 / SR)
  spec[(freqs < lo) | (freqs > hi)] = 0
  sig = np.fft.irfft(spec, n)
  return (sig / (np.sqrt(np.mean(sig**2)) + 1e-8) * target_rms).astype(np.float32)


def silence(dur: float) -> np.ndarray:
  return np.zeros(int(dur * SR), dtype=np.float32)


def _word(w: str, start: float, end: float, conf: float = 0.9) -> dict:
  return {"word": w, "start": round(start, 3), "end": round(end, 3), "confidence": conf}


def build_clips() -> list[dict]:
  clips: list[dict] = []

  # 1) Held fricative "ssssnake" -> fricative prolongation on snake, no block.
  audio = np.concatenate([
    vowel(1.06),                       # I        [0.00, 1.06]
    fricative(0.12), vowel(0.44),      # see      [1.06, 1.62]
    vowel(0.56),                       # a        [1.62, 2.18]
    fricative(0.85), vowel(0.27),      # snake    [2.18, 3.30] (held /s/ then vowel)
  ])
  clips.append({
    "clip_id": "syn_held_fricative_snake",
    "audio": audio,
    "child_age": 8,
    "reference_phrase": "I see a snake",
    "transcript": "I see a snake.",
    "words": [_word("I", 0, 1.06), _word("see", 1.06, 1.62),
              _word("a", 1.62, 2.18), _word("snake.", 2.18, 3.30)],
    "is_fluent": False,
    "labels": [{"type": "prolongation", "start": 2.18, "end": 3.03,
                "severity": "moderate", "word": "snake", "sound": "s"}],
  })

  # 2) Fluent "I see a snake" -> nothing (false-positive test clip).
  audio = np.concatenate([
    vowel(1.0),
    fricative(0.10), vowel(0.40),
    vowel(0.50),
    fricative(0.10), vowel(0.50),
  ])
  clips.append({
    "clip_id": "syn_fluent_snake",
    "audio": audio,
    "child_age": 8,
    "reference_phrase": "I see a snake",
    "transcript": "I see a snake.",
    "words": [_word("I", 0, 1.0), _word("see", 1.0, 1.5),
              _word("a", 1.5, 2.0), _word("snake.", 2.0, 2.6)],
    "is_fluent": True,
    "labels": [],
  })

  # 3) Silent block before "snake" -> one block.
  audio = np.concatenate([
    vowel(1.0),                        # I     [0.00, 1.00]
    fricative(0.10), vowel(0.40),      # see   [1.00, 1.50]
    vowel(0.50),                       # a     [1.50, 2.00]
    silence(0.5),                      # BLOCK [2.00, 2.50]
    fricative(0.10), vowel(0.50),      # snake [2.50, 3.10]
  ])
  clips.append({
    "clip_id": "syn_block_before_snake",
    "audio": audio,
    "child_age": 8,
    "reference_phrase": "I see a snake",
    "transcript": "I see a snake.",
    "words": [_word("I", 0, 1.0), _word("see", 1.0, 1.5),
              _word("a", 1.5, 2.0), _word("snake.", 2.5, 3.1)],
    "is_fluent": False,
    "labels": [{"type": "block", "start": 2.0, "end": 2.5,
                "severity": "moderate", "word": "snake"}],
  })

  # 4) Held vowel "goooo" -> voiced prolongation.
  audio = np.concatenate([
    vowel(0.15),                       # onset
    vowel(0.70, moving=False),         # held vowel
    vowel(0.10),                       # offset
  ])
  clips.append({
    "clip_id": "syn_held_vowel_go",
    "audio": audio,
    "child_age": 8,
    "reference_phrase": "go",
    "transcript": "go",
    "words": [_word("go", 0.0, 0.95)],
    "is_fluent": False,
    "labels": [{"type": "prolongation", "start": 0.15, "end": 0.85,
                "severity": "moderate", "word": "go"}],
  })

  # 5) Fluent "I want the ball" -> nothing (false-positive test clip).
  audio = np.concatenate([
    vowel(0.5), vowel(0.5, f0=170), vowel(0.4, f0=190),
    fricative(0.10), vowel(0.5, f0=160),
  ])
  clips.append({
    "clip_id": "syn_fluent_want_ball",
    "audio": audio,
    "child_age": 10,
    "reference_phrase": "I want the ball",
    "transcript": "I want the ball.",
    "words": [_word("I", 0, 0.5), _word("want", 0.5, 1.0),
              _word("the", 1.0, 1.4), _word("ball.", 1.4, 2.0)],
    "is_fluent": True,
    "labels": [],
  })

  return clips


def main() -> int:
  OUT_DIR.mkdir(parents=True, exist_ok=True)
  clips = build_clips()
  lines: list[str] = []
  for c in clips:
    wav_path = OUT_DIR / f"{c['clip_id']}.wav"
    sf.write(str(wav_path), c["audio"], SR)
    record = {
      "clip_id": c["clip_id"],
      "audio_path": str(wav_path.relative_to(ROOT)),
      "child_age": c["child_age"],
      "reference_phrase": c["reference_phrase"],
      "transcript": c["transcript"],
      "words": c["words"],
      "is_fluent": c["is_fluent"],
      "labels": c["labels"],
      "annotator": "synthetic",
    }
    lines.append(json.dumps(record))

  with open(LABELS, "w") as f:
    f.write("\n".join(lines) + "\n")

  print(f"Wrote {len(clips)} synthetic clips to {OUT_DIR}")
  print(f"Wrote labels to {LABELS}")
  print("Run: .venv/bin/python -m scripts.evaluate")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
